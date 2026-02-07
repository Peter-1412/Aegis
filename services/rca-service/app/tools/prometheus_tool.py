from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time
from typing import Any

import httpx
from langchain_core.tools import tool

from config.config import settings


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_json_payload(text: str | None) -> dict | None:
    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]
            raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    in_str = False
    escape = False
    depth = 0
    start_idx = None
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start_idx is not None:
                candidate = text[start_idx : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    start_idx = None
    return None


_PROM_CACHE: dict[tuple[Any, ...], dict] = {}


@tool(
    "prometheus_query_range",
    description="按时间范围执行 PromQL 查询，返回时间序列数据及原始结果概要，适用于 Todo_List 项目的服务健康与资源分析。",
)
async def prometheus_query_range(
    promql: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    step: str = "60s",
    query: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    promql_stripped = (promql or query or "").strip()
    start_iso = (start_iso or start or "").strip()
    end_iso = (end_iso or end or "").strip()
    
    # Default to last 15 minutes if not provided
    now = datetime.now(timezone.utc)
    if not start_iso:
        start_iso = (now - timedelta(minutes=15)).isoformat()
    if not end_iso:
        end_iso = now.isoformat()
        
    t0 = time.monotonic()
    payload = _extract_json_payload(promql_stripped)
    if isinstance(payload, dict):
        promql_stripped = str(payload.get("query") or payload.get("promql") or promql_stripped).strip()
        if not start_iso:
            start_iso = str(payload.get("start") or payload.get("start_iso") or "").strip()
        if not end_iso:
            end_iso = str(payload.get("end") or payload.get("end_iso") or "").strip()
        if payload.get("step"):
            step = str(payload.get("step") or step)
    if not promql_stripped:
        return {
            "error": "invalid_promql",
            "message": "promql 不能为空",
        }
    if not start_iso or not end_iso:
        return {
            "error": "invalid_datetime",
            "message": "start_iso 和 end_iso 不能为空",
            "promql": promql_stripped,
            "start_raw": start_iso or None,
            "end_raw": end_iso or None,
        }
    try:
        start = _parse_dt(start_iso)
        end = _parse_dt(end_iso)
    except Exception as exc:
        return {
            "error": "invalid_datetime",
            "message": str(exc),
            "promql": promql_stripped,
            "start_raw": start_iso,
            "end_raw": end_iso,
        }
    if end <= start:
        return {
            "error": "invalid_range",
            "message": "end 必须大于 start",
            "promql": promql_stripped,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
    step_stripped = (step or "").strip()
    if not step_stripped:
        step_stripped = "60s"
    cache_key = (promql_stripped, start.isoformat(), end.isoformat(), step_stripped)
    if cache_key in _PROM_CACHE:
        logging.info("prometheus_query_range cache hit, key=%s", cache_key)
        return _PROM_CACHE[cache_key]
    params = {
        "query": promql_stripped,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step_stripped,
    }
    url = f"{settings.prometheus_base_url.rstrip('/')}/api/v1/query_range"
    logging.info(
        "prometheus_query_range start, url=%s, promql=%s, start=%s, end=%s, step=%s",
        url,
        promql_stripped,
        start.isoformat(),
        end.isoformat(),
        step_stripped,
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
                r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as exc:
            last_exc = exc
            logging.warning(
                "prometheus_query_range request failed, attempt=%s, url=%s, error=%s",
                attempt + 1,
                url,
                exc,
            )
    else:
        return {
            "error": "prometheus_request_failed",
            "message": str(last_exc) if last_exc else "unknown error",
            "promql": promql_stripped,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step_stripped,
        }
    series = []
    for item in data.get("data", {}).get("result", []) or []:
        metric = item.get("metric", {}) or {}
        values = []
        for ts, val in item.get("values") or []:
            values.append([ts, val])
        series.append({"metric": metric, "values": values})
    result = {
        "promql": promql_stripped,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step_stripped,
        "result_type": data.get("data", {}).get("resultType"),
        "series": series,
    }
    dt = time.monotonic() - t0
    logging.info(
        "prometheus_query_range done, duration_s=%.3f, series=%s",
        dt,
        len(series),
    )
    _PROM_CACHE[cache_key] = result
    return result
