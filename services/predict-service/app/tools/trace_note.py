from __future__ import annotations

from langchain_core.tools import tool


@tool("trace_note", description="记录本轮工具调用前的计划/原因（用于前端回放）。")
async def trace_note(note: str) -> str:
    return note

