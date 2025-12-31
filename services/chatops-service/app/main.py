from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import json
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, ChatOpsQueryRequest, ChatOpsQueryResponse, TimeRange, TraceStep
from .settings import settings
from .agent.executor import build_executor
from .memory.store import get_memory
from .tools import build_tools

from langchain_core.callbacks import AsyncCallbackHandler


app = FastAPI(title="ChatOps Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
loki = LokiClient(settings.loki_base_url, settings.loki_tenant_id, settings.request_timeout_s)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_timerange(time_range: TimeRange | None) -> tuple[datetime, datetime]:
    if time_range is None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=30)
        return start, end
    if time_range.last_minutes is not None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=time_range.last_minutes)
        return start, end
    if time_range.start is None or time_range.end is None:
        raise HTTPException(status_code=400, detail="必须指定time_range.start与time_range.end，或者last_minutes。")
    return _ensure_utc(time_range.start), _ensure_utc(time_range.end)

def _to_cst(dt: datetime) -> datetime:
    return _ensure_utc(dt).astimezone(timezone(timedelta(hours=8)))


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _extract_used_logql(intermediate_steps) -> str | None:
    if not intermediate_steps:
        return None
    for pair in reversed(intermediate_steps):
        try:
            action, observation = pair
        except Exception:
            continue
        tool = getattr(action, "tool", "") or ""
        if tool != "loki_query_range_lines":
            continue
        tool_input = getattr(action, "tool_input", None)
        logql = None
        if isinstance(tool_input, dict):
            logql = tool_input.get("logql")
        elif isinstance(tool_input, str):
            try:
                data = json.loads(tool_input)
                if isinstance(data, dict):
                    logql = data.get("logql")
            except Exception:
                logql = None
        if not logql and isinstance(observation, dict):
            logql = observation.get("logql")
        if isinstance(logql, str) and logql.strip():
            return logql.strip()
    return None


def _build_trace(intermediate_steps) -> AgentTrace:
    steps: list[TraceStep] = []
    for idx, pair in enumerate(intermediate_steps or []):
        try:
            action, observation = pair
        except Exception:
            continue
        tool = str(getattr(action, "tool", "") or "")
        tool_input = getattr(action, "tool_input", None)
        log = getattr(action, "log", None)
        obs_text = _stringify(observation)
        if len(obs_text) > 8000:
            obs_text = obs_text[:8000] + "\n...(truncated)"
        inp_text = _stringify(tool_input)
        if len(inp_text) > 4000:
            inp_text = inp_text[:4000] + "\n...(truncated)"
        steps.append(
            TraceStep(
                index=idx,
                tool=tool,
                tool_input=inp_text or None,
                observation=obs_text or None,
                log=str(log) if log else None,
            )
        )
    return AgentTrace(steps=steps)


class ChatOpsStreamHandler(AsyncCallbackHandler):
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def on_llm_new_token(self, token: str, **kwargs):
        await self.queue.put(
            {
                "event": "llm_token",
                "token": token,
            }
        )

    async def on_agent_action(self, action, **kwargs):
        tool = getattr(action, "tool", "") or ""
        tool_input = getattr(action, "tool_input", None)
        log = getattr(action, "log", None)
        await self.queue.put(
            {
                "event": "agent_action",
                "tool": str(tool),
                "tool_input": _stringify(tool_input),
                "log": str(log) if log else None,
            }
        )

    async def on_tool_start(self, serialized, input_str, **kwargs):
        name = None
        if isinstance(serialized, dict):
            name = serialized.get("name") or serialized.get("tool")
        if not name:
            name = str(serialized)
        await self.queue.put(
            {
                "event": "tool_start",
                "tool": name,
                "tool_input": _stringify(input_str),
            }
        )

    async def on_tool_end(self, output, **kwargs):
        await self.queue.put(
            {
                "event": "tool_end",
                "observation": _stringify(output),
            }
        )


async def _run_chatops(req: ChatOpsQueryRequest, callbacks: list | None = None) -> ChatOpsQueryResponse:
    start, end = _resolve_timerange(req.time_range)
    if end <= start:
        raise HTTPException(status_code=400, detail="end必须大于start。")

    start_cst = _to_cst(start)
    end_cst = _to_cst(end)

    try:
        service_values = await loki.label_values(settings.loki_service_label_key)
    except Exception:
        service_values = []

    llm = get_llm(streaming=callbacks is not None)
    tools = build_tools(loki)
    memory = get_memory(req.session_id)
    executor = build_executor(llm, tools, memory)

    services_hint = "、".join(service_values[:50]) if service_values else "未知"
    agent_input = (
        f"用户问题：{req.question}\n"
        f"时间范围（CST）：{start_cst.isoformat()} ~ {end_cst.isoformat()}\n"
        f"已知服务列表（可能不完整）：{services_hint}\n"
        "请在必要时调用工具查询Loki，然后给出最终答案。"
    )
    config = {"callbacks": callbacks} if callbacks else None
    out = await executor.ainvoke({"input": agent_input}, config=config)
    answer = str(out.get("output") or "").strip()
    intermediate_steps = out.get("intermediate_steps")
    trace = _build_trace(intermediate_steps)
    used_logql = _extract_used_logql(intermediate_steps)
    return ChatOpsQueryResponse(answer=answer, used_logql=used_logql, start=start_cst, end=end_cst, trace=trace)


@app.post("/api/chatops/query", response_model=ChatOpsQueryResponse)
async def query(req: ChatOpsQueryRequest) -> ChatOpsQueryResponse:
    return await _run_chatops(req)


@app.post("/api/chatops/query/stream")
async def query_stream(req: ChatOpsQueryRequest):
    queue: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            handler = ChatOpsStreamHandler(queue)
            start, end = _resolve_timerange(req.time_range)
            start_cst = _to_cst(start)
            end_cst = _to_cst(end)
            await queue.put(
                {
                    "event": "start",
                    "start": start_cst.isoformat(),
                    "end": end_cst.isoformat(),
                }
            )
            res = await _run_chatops(req, callbacks=[handler])
            meta = {
                "event": "final",
                "answer": res.answer,
                "used_logql": res.used_logql,
                "start": res.start.isoformat() if res.start else None,
                "end": res.end.isoformat() if res.end else None,
                "trace": res.trace.dict() if res.trace else None,
            }
            await queue.put(meta)
        except Exception as exc:
            await queue.put({"event": "error", "message": str(exc)})
        finally:
            await queue.put({"event": "end"})

    asyncio.create_task(runner())

    async def iterator() -> AsyncIterator[bytes]:
        while True:
            item = await queue.get()
            data = json.dumps(item, ensure_ascii=False) + "\n"
            yield data.encode("utf-8")
            if item.get("event") == "end":
                break

    return StreamingResponse(iterator(), media_type="application/x-ndjson")
