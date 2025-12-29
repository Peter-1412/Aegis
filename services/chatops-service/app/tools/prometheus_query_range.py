from __future__ import annotations

from datetime import datetime, timezone

import httpx
from langchain_core.tools import tool

from ..settings import settings


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@tool(
    "prometheus_query_range",
    description="按时间范围执行 PromQL 查询，返回时间序列数据及元信息，适用于 Todo_List 项目的各类服务与基础设施指标分析。",
)
async def prometheus_query_range(
    promql: str,
    start_iso: str,
    end_iso: str,
    step: str = "60s",
) -> dict:
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
    params = {
        "query": promql,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            r = await client.get(f"{settings.prometheus_base_url.rstrip('/')}/api/v1/query_range", params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {
            "error": "prometheus_request_failed",
            "message": str(exc),
            "promql": promql,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step,
        }
    series = []
    for item in data.get("data", {}).get("result", []) or []:
        metric = item.get("metric", {}) or {}
        values = []
        for ts, val in item.get("values") or []:
            values.append([ts, val])
        series.append({"metric": metric, "values": values})
    return {
        "promql": promql,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
        "result_type": data.get("data", {}).get("resultType"),
        "series": series,
    }
