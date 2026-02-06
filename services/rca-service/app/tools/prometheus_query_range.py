from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from ..settings import settings


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_PROM_CACHE: dict[tuple[Any, ...], dict] = {}


@tool(
    "prometheus_query_range",
    description="按时间范围执行 PromQL 查询，返回时间序列数据及原始结果概要，适用于 Todo_List 项目的服务健康与资源分析。",
)
async def prometheus_query_range(
    promql: str,
    start_iso: str,
    end_iso: str,
    step: str = "60s",
) -> dict:
    promql_stripped = (promql or "").strip()
    if not promql_stripped:
        return {
            "error": "invalid_promql",
            "message": "promql 不能为空",
        }
    try:
        start = _parse_dt(start_iso)
        end = _parse_dt(end_iso)
    except Exception as exc:
        return {
            "error": "invalid_datetime",
            "message": str(exc),
            "promql": promql,
            "start_raw": start_iso,
            "end_raw": end_iso,
        }
    if end <= start:
        return {
            "error": "invalid_range",
            "message": "end 必须大于 start",
            "promql": promql,
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
    _PROM_CACHE[cache_key] = result
    return result
