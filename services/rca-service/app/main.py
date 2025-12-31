from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import json
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.callbacks import AsyncCallbackHandler

from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, RCAOutput, RCARequest, RCAResponse, TraceStep
from .settings import settings
from .agent.executor import build_executor
from .memory.store import get_memory
from .tools import build_tools


app = FastAPI(title="RCA Service", version="0.1.0")
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


_CST = timezone(timedelta(hours=8))


def _ensure_cst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_CST)
    return dt.astimezone(_CST)


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


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


class RCAStreamHandler(AsyncCallbackHandler):
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


async def _run_rca(req: RCARequest, callbacks: list | None = None) -> RCAResponse:
    start = _ensure_cst(req.time_range.start)
    end = _ensure_cst(req.time_range.end)
    if end <= start:
        raise HTTPException(status_code=400, detail="end必须大于start。")

    llm = get_llm(streaming=callbacks is not None)
    tools = build_tools(loki)
    memory = get_memory(req.session_id)
    executor = build_executor(llm, tools, memory)

    agent_input = (
        f"故障描述：{req.description}\n"
        f"时间范围（CST，UTC+8）：{start.isoformat()} ~ {end.isoformat()}\n\n"
        "请按以下步骤执行：\n"
        "1) 调用工具rca_collect_evidence获取日志证据\n"
        "2) 基于证据输出RCA结论\n\n"
        "输出必须是JSON对象，字段为：summary, suspected_service, root_cause, evidence, suggested_actions。"
    )
    config = {"callbacks": callbacks} if callbacks else None
    res = await executor.ainvoke({"input": agent_input}, config=config)
    raw = str(res.get("output") or "")
    try:
        out = RCAOutput.model_validate_json(raw)
    except Exception:
        out = RCAOutput(summary=raw.strip() or "模型输出为空。")
    trace = _build_trace(res.get("intermediate_steps"))
    return RCAResponse(
        summary=out.summary,
        suspected_service=out.suspected_service,
        root_cause=out.root_cause,
        evidence=out.evidence or [],
        suggested_actions=out.suggested_actions or [],
        trace=trace,
    )


@app.post("/api/rca/analyze", response_model=RCAResponse)
async def analyze(req: RCARequest) -> RCAResponse:
    return await _run_rca(req)


@app.post("/api/rca/analyze/stream")
async def analyze_stream(req: RCARequest):
    queue: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            handler = RCAStreamHandler(queue)
            start = _ensure_cst(req.time_range.start)
            end = _ensure_cst(req.time_range.end)
            await queue.put(
                {
                    "event": "start",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
            )
            res = await _run_rca(req, callbacks=[handler])
            meta = {
                "event": "final",
                "summary": res.summary,
                "suspected_service": res.suspected_service,
                "root_cause": res.root_cause,
                "evidence": res.evidence,
                "suggested_actions": res.suggested_actions,
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
