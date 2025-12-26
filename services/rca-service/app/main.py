from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, RCAOutput, RCARequest, RCAResponse, TraceStep
from .settings import settings
from .agent.executor import build_executor
from .memory.store import get_memory
from .tools.rca import build_tools


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


@app.post("/api/rca/analyze", response_model=RCAResponse)
async def analyze(req: RCARequest) -> RCAResponse:
    start = _ensure_cst(req.time_range.start)
    end = _ensure_cst(req.time_range.end)
    if end <= start:
        raise HTTPException(status_code=400, detail="end必须大于start。")

    llm = get_llm()
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
    res = await executor.ainvoke({"input": agent_input})
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
