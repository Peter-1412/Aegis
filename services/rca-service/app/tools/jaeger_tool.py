from __future__ import annotations

from datetime import datetime, timezone
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


_JAEGER_CACHE: dict[tuple[Any, ...], dict] = {}


@tool(
    "jaeger_query_traces",
    description=(
        "从 Jaeger 查询指定服务在给定时间范围内的代表性调用链，用于辅助根因分析。"
        "该工具只读取数据，不会对集群或应用产生任何写入或变更。"
    ),
)
async def jaeger_query_traces(
    service: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
    limit: int = 10,
) -> dict:
    t0 = time.monotonic()
    base_url = (settings.jaeger_base_url or "").rstrip("/")
    service_name = (service or "").strip()
    if not base_url:
        return {
            "error": "jaeger_not_configured",
            "message": "jaeger_base_url 未配置，无法查询调用链。",
            "service": service_name,
        }
    if not service_name:
        return {
            "error": "invalid_service",
            "message": "service 不能为空",
        }
        
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
            "service": service_name,
            "start_raw": start_iso,
            "end_raw": end_iso,
        }
    if end <= start:
        return {
            "error": "invalid_range",
            "message": "end 必须大于 start",
            "service": service_name,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
    limit_valid = max(1, min(limit, 100))
    cache_key = (service_name, start.isoformat(), end.isoformat(), limit_valid)
    if cache_key in _JAEGER_CACHE:
        logging.info("jaeger_query_traces cache hit, key=%s", cache_key)
        return _JAEGER_CACHE[cache_key]
    params = {
        "service": service_name,
        "start": int(start.timestamp() * 1_000_000),
        "end": int(end.timestamp() * 1_000_000),
        "limit": limit_valid,
    }
    url = f"{base_url}/api/traces"
    logging.info(
        "jaeger_query_traces start, url=%s, service=%s, start=%s, end=%s, limit=%s",
        url,
        service_name,
        start.isoformat(),
        end.isoformat(),
        limit_valid,
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
                "jaeger_query_traces request failed, attempt=%s, url=%s, error=%s",
                attempt + 1,
                url,
                exc,
            )
    else:
        return {
            "error": "jaeger_request_failed",
            "message": str(last_exc) if last_exc else "unknown error",
            "service": service_name,
            "url": url,
        }
    traces_summary: list[dict] = []
    for trace in data.get("data") or []:
        trace_id = trace.get("traceID")
        spans = trace.get("spans") or []
        services = {span.get("process", {}).get("serviceName") for span in spans}
        services = {s for s in services if s}
        duration_us = trace.get("duration")
        traces_summary.append(
            {
                "trace_id": trace_id,
                "duration_us": duration_us,
                "service_count": len(services),
                "services": sorted(list(services)),
                "span_count": len(spans),
            }
        )
    result = {
        "service": service_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": limit_valid,
        "trace_summaries": traces_summary,
    }
    dt = time.monotonic() - t0
    logging.info("jaeger_query_traces done, duration_s=%.3f, traces=%s", dt, len(traces_summary))
    _JAEGER_CACHE[cache_key] = result
    return result
