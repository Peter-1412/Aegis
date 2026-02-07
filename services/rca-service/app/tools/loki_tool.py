from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any

import httpx
from langchain_core.tools import tool

from config.config import settings


def _dt_to_ns(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


@dataclass(frozen=True)
class LokiQueryResult:
    raw: dict

    def flatten_log_lines(self, limit: int | None = None) -> list[str]:
        data = self.raw.get("data", {})
        results = data.get("result", []) or []
        lines: list[str] = []
        for item in results:
            stream = item.get("stream", {}) or {}
            values = item.get("values", []) or []
            for ts, line in values:
                labels = ",".join(f"{k}={v}" for k, v in sorted(stream.items()))
                lines.append(f"{ts} [{labels}] {line}")
        if limit is not None:
            return lines[:limit]
        return lines


class LokiClient:
    def __init__(self, base_url: str, tenant_id: str | None, timeout_s: float):
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        if self._tenant_id:
            return {"X-Scope-OrgID": self._tenant_id}
        return {}

    async def label_values(self, label: str) -> list[str]:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/label/{label}/values", headers=self._headers())
        r.raise_for_status()
        values = (r.json().get("data") or [])[:]
        dt = time.monotonic() - t0
        logging.info("loki label_values done, label=%s, duration_s=%.3f, values=%s", label, dt, len(values))
        return values

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 200,
        direction: str = "BACKWARD",
    ) -> LokiQueryResult:
        t0 = time.monotonic()
        params: dict[str, str | int] = {
            "query": query,
            "start": _dt_to_ns(start),
            "end": _dt_to_ns(end),
            "limit": limit,
            "direction": direction,
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.get(f"{self._base_url}/loki/api/v1/query_range", params=params, headers=self._headers())
        r.raise_for_status()
        res = LokiQueryResult(raw=r.json())
        dt = time.monotonic() - t0
        logging.info("loki query_range done, duration_s=%.3f, limit=%s", dt, limit)
        return res


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _prioritize_services(all_services: list[str], patterns: list[str] | None, max_services: int) -> list[str]:
    if not all_services:
        return []
    patterns = [p.lower() for p in (patterns or []) if p]
    if not patterns:
        return all_services[:max_services]
    selected: list[str] = []
    for s in all_services:
        lower = s.lower()
        if any(p in lower for p in patterns):
            selected.append(s)
    for s in all_services:
        if s not in selected:
            selected.append(s)
    return selected[:max_services]


_LOKI_CACHE: dict[tuple[Any, ...], dict] = {}


def make_loki_collect_evidence(loki: LokiClient):
    @tool(
        "loki_collect_evidence",
        description=(
            "从 Loki 批量收集错误/异常相关日志样本，作为 RCA 证据输入。"
            "可以通过 service_patterns 聚焦某些服务名称（例如 ['user', 'auth', 'todo']），"
            "通过 text_patterns 聚焦日志内容关键词（例如 ['login', 'peter', '401']）。"
        ),
    )
    async def loki_collect_evidence(
        start_iso: str | None = None,
        end_iso: str | None = None,
        max_services: int = 50,
        per_service_log_limit: int = 200,
        max_total_lines: int = 200,
        service_patterns: list[str] | None = None,
        text_patterns: list[str] | None = None,
    ) -> dict:
        t0 = time.monotonic()
        
        # Default to last 15 minutes if not provided
        now = datetime.now(timezone.utc)
        if not start_iso:
            start_iso = (now - timedelta(minutes=15)).isoformat()
        if not end_iso:
            end_iso = now.isoformat()
            
        try:
            start = _parse_dt(start_iso)
            end = _parse_dt(end_iso)
        except Exception as exc:
            return {
                "error": "invalid_datetime",
                "message": str(exc),
                "start_raw": start_iso,
                "end_raw": end_iso,
            }
        if end <= start:
            return {
                "error": "invalid_range",
                "message": "end must be greater than start",
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        max_services_valid = max(1, min(max_services, 100))
        per_service_log_limit_valid = max(1, min(per_service_log_limit, settings.per_service_log_limit))
        max_total_lines_valid = max(1, min(max_total_lines, settings.max_total_evidence_lines))
        cache_key = (
            start.isoformat(),
            end.isoformat(),
            max_services_valid,
            per_service_log_limit_valid,
            max_total_lines_valid,
            tuple(sorted(service_patterns or [])),
            tuple(sorted(text_patterns or [])),
        )
        if cache_key in _LOKI_CACHE:
            logging.info("loki_collect_evidence cache hit, key=%s", cache_key)
            return _LOKI_CACHE[cache_key]
        logging.info(
            "loki_collect_evidence start, start=%s, end=%s, max_services=%s, per_service_log_limit=%s, max_total_lines=%s, service_patterns=%s, text_patterns=%s",
            start.isoformat(),
            end.isoformat(),
            max_services_valid,
            per_service_log_limit_valid,
            max_total_lines_valid,
            service_patterns,
            text_patterns,
        )
        all_services: list[str] = []
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                all_services = await loki.label_values(settings.loki_service_label_key)
                break
            except Exception as exc:
                last_exc = exc
                logging.warning(
                    "loki label_values failed, attempt=%s, label_key=%s, error=%s",
                    attempt + 1,
                    settings.loki_service_label_key,
                    exc,
                )
        if not all_services and last_exc is not None:
            logging.exception("loki label_values failed after retries: %s", last_exc)
        services = _prioritize_services(all_services, service_patterns, max_services_valid)
        error_regex = (
            r'(?i)('
            r'error|exception|traceback|panic|fatal|timeout|'
            r'unauthorized|forbidden|denied|permission denied|'
            r'authentication failed|login failed|invalid password|'
            r'4\d\d|5\d\d|'
            r'connection refused|connection reset'
            r')'
        )
        extra_patterns = [p for p in (text_patterns or []) if p]
        seen: set[str] = set()
        evidence_lines: list[str] = []
        for service in services:
            selector = settings.loki_selector_template.format(
                label_key=settings.loki_service_label_key,
                service=service,
            )
            query = f'{selector} |~ "{error_regex}"'
            last_q_exc: Exception | None = None
            for attempt in range(3):
                try:
                    res = await loki.query_range(query, start=start, end=end, limit=per_service_log_limit_valid)
                    lines = res.flatten_log_lines(limit=per_service_log_limit_valid)
                    for line in lines:
                        if line not in seen:
                            seen.add(line)
                            evidence_lines.append(line)
                            if len(evidence_lines) >= max_total_lines_valid:
                                break
                    break
                except Exception as exc:
                    last_q_exc = exc
                    logging.warning(
                        "loki query_range error regex failed, attempt=%s, service=%s, error=%s",
                        attempt + 1,
                        service,
                        exc,
                    )
            if last_q_exc is not None and not evidence_lines:
                logging.exception("loki query_range error regex failed after retries for service=%s: %s", service, last_q_exc)
            if len(evidence_lines) >= max_total_lines_valid:
                break
            for pat in extra_patterns:
                safe_pat = pat.replace('"', '\\"')
                extra_query = f'{selector} |~ "{safe_pat}"'
                last_extra_exc: Exception | None = None
                for attempt in range(3):
                    try:
                        res2 = await loki.query_range(extra_query, start=start, end=end, limit=per_service_log_limit_valid)
                        lines2 = res2.flatten_log_lines(limit=per_service_log_limit_valid)
                        for line in lines2:
                            if line not in seen:
                                seen.add(line)
                                evidence_lines.append(line)
                                if len(evidence_lines) >= max_total_lines_valid:
                                    break
                        break
                    except Exception as exc:
                        last_extra_exc = exc
                        logging.warning(
                            "loki query_range extra pattern failed, attempt=%s, service=%s, pattern=%s, error=%s",
                            attempt + 1,
                            service,
                            pat,
                            exc,
                        )
                if last_extra_exc is not None and not evidence_lines:
                    logging.exception(
                        "loki query_range extra pattern failed after retries for service=%s, pattern=%s: %s",
                        service,
                        pat,
                        last_extra_exc,
                    )
                if len(evidence_lines) >= max_total_lines_valid:
                    break
            if len(evidence_lines) >= max_total_lines_valid:
                break
        if not evidence_lines:
            evidence_lines = ["在该时间范围内未检索到明显的错误或相关日志（基于通用error正则与关键词搜索）。"]
        result = {
            "services": services,
            "evidence_lines": evidence_lines[:max_total_lines_valid],
            "loki_api": {"path": "/loki/api/v1/query_range"},
        }
        dt = time.monotonic() - t0
        logging.info(
            "loki_collect_evidence done, duration_s=%.3f, services=%s, lines=%s",
            dt,
            len(services),
            len(result["evidence_lines"]),
        )
        _LOKI_CACHE[cache_key] = result
        return result

    return loki_collect_evidence
