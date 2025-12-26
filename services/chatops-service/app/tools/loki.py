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


def build_tools(loki: LokiClient):
    @tool("trace_note", description="记录本轮工具调用前的计划/原因（用于前端回放）。")
    async def trace_note(note: str) -> str:
        return note

    @tool("loki_query_range_lines", description="按时间范围执行 LogQL 查询，返回日志行及元信息。")
    async def loki_query_range_lines(
        logql: str,
        start_iso: str,
        end_iso: str,
        limit: int = 200,
        direction: str = "BACKWARD",
        step_seconds: int | None = None,
    ) -> dict:
        start = _parse_dt(start_iso)
        end = _parse_dt(end_iso)
        res = await loki.query_range(
            logql,
            start=start,
            end=end,
            limit=limit,
            direction=direction,
            step_seconds=step_seconds,
        )
        lines = res.flatten_log_lines(limit=limit)
        return {
            "logql": logql,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": limit,
            "direction": direction,
            "step_seconds": step_seconds,
            "line_count": len(lines),
            "lines": lines,
        }

    return [trace_note, loki_query_range_lines]

