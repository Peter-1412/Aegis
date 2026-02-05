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
    "jaeger_query_traces",
    description=(
        "从 Jaeger 查询指定服务在给定时间范围内的代表性调用链，用于辅助根因分析。"
        "该工具只读取数据，不会对集群或应用产生任何写入或变更。"
    ),
)
async def jaeger_query_traces(
    service: str,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> dict:
    base_url = (settings.jaeger_base_url or "").rstrip("/")
    if not base_url:
        return {
            "error": "jaeger_not_configured",
            "message": "jaeger_base_url 未配置，无法查询调用链。",
            "service": service,
        }
    try:
        start = _parse_dt(start_iso)
        end = _parse_dt(end_iso)
    except Exception as exc:
        return {
            "error": "invalid_datetime",
            "message": str(exc),
            "service": service,
            "start_raw": start_iso,
            "end_raw": end_iso,
        }

    params = {
        "service": service,
        "start": int(start.timestamp() * 1_000_000),
        "end": int(end.timestamp() * 1_000_000),
        "limit": limit,
    }
    url = f"{base_url}/api/traces"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {
            "error": "jaeger_request_failed",
            "message": str(exc),
            "service": service,
            "url": url,
        }

    traces_summary: list[dict] = []
    for trace in data.get("data") or []:
        trace_id = trace.get("traceID")
        spans = trace.get("spans") or []
        root_span = spans[0] if spans else {}
        operation_name = root_span.get("operationName")
        duration_us = trace.get("duration")
        tags = root_span.get("tags") or []
        error_tags = [t for t in tags if t.get("key") in ("error", "otel.status_code") and str(t.get("value")).lower() in ("true", "error")]
        traces_summary.append(
            {
                "trace_id": trace_id,
                "operation": operation_name,
                "duration_us": duration_us,
                "has_error_tag": bool(error_tags),
            }
        )

    return {
        "service": service,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": limit,
        "trace_count": len(traces_summary),
        "traces": traces_summary,
        "jaeger_api": {"path": "/api/traces"},
    }
