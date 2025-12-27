from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from ..loki_client import LokiClient
from ..settings import settings


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


def make_rca_collect_evidence(loki: LokiClient):
    @tool(
        "rca_collect_evidence",
        description=(
            "从 Loki 批量收集错误/异常相关日志样本，作为 RCA 证据输入。"
            "可以通过 service_patterns 聚焦某些服务名称（例如 ['user', 'auth', 'todo']），"
            "通过 text_patterns 聚焦日志内容关键词（例如 ['login', 'peter', '401']）。"
        ),
    )
    async def rca_collect_evidence(
        start_iso: str,
        end_iso: str,
        max_services: int = 50,
        per_service_log_limit: int = 200,
        max_total_lines: int = 200,
        service_patterns: list[str] | None = None,
        text_patterns: list[str] | None = None,
    ) -> dict:
        start = _parse_dt(start_iso)
        end = _parse_dt(end_iso)
        try:
            all_services = await loki.label_values(settings.loki_service_label_key)
        except Exception:
            all_services = []

        services = _prioritize_services(all_services, service_patterns, max_services)

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
            try:
                res = await loki.query_range(query, start=start, end=end, limit=per_service_log_limit)
                lines = res.flatten_log_lines(limit=per_service_log_limit)
                for line in lines:
                    if line not in seen:
                        seen.add(line)
                        evidence_lines.append(line)
                        if len(evidence_lines) >= max_total_lines:
                            break
            except Exception:
                pass
            if len(evidence_lines) >= max_total_lines:
                break

            for pat in extra_patterns:
                safe_pat = pat.replace('"', '\\"')
                extra_query = f'{selector} |~ "{safe_pat}"'
                try:
                    res2 = await loki.query_range(extra_query, start=start, end=end, limit=per_service_log_limit)
                    lines2 = res2.flatten_log_lines(limit=per_service_log_limit)
                    for line in lines2:
                        if line not in seen:
                            seen.add(line)
                            evidence_lines.append(line)
                            if len(evidence_lines) >= max_total_lines:
                                break
                except Exception:
                    continue
                if len(evidence_lines) >= max_total_lines:
                    break
            if len(evidence_lines) >= max_total_lines:
                break

        if not evidence_lines:
            evidence_lines = ["在该时间范围内未检索到明显的错误或相关日志（基于通用error正则与关键词搜索）。"]
        return {
            "services": services,
            "evidence_lines": evidence_lines[:max_total_lines],
            "loki_api": {"path": "/loki/api/v1/query_range"},
        }

    return rca_collect_evidence

