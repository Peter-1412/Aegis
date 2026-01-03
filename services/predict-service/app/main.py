from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import json
from typing import AsyncIterator

import logging
import uuid

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.prompts import ChatPromptTemplate

from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, LikelyFailures, PredictRequest, PredictResponse, TraceStep
from .settings import settings
from .agent.executor import build_executor
from .memory.store import get_memory
from .tools import build_tools


class _HealthzAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if isinstance(args, tuple) and len(args) >= 2:
                req = args[1]
                if isinstance(req, str) and "/healthz" in req:
                    return False
            msg = record.getMessage()
            if "/healthz" in msg:
                return False
        except Exception:
            return True
        return True


logging.getLogger("uvicorn.access").addFilter(_HealthzAccessFilter())


app = FastAPI(title="Predict Service", version="0.1.0")
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


def _selector_for_service(service: str) -> str:
    return settings.loki_selector_template.format(label_key=settings.loki_service_label_key, service=service)


def _risk_from_counts(counts: np.ndarray) -> float:
    if counts.size == 0:
        return 0.1
    mean = float(np.mean(counts))
    p95 = float(np.percentile(counts, 95))
    last = float(counts[-1])
    recent = float(np.mean(counts[-12:])) if counts.size >= 12 else float(np.mean(counts))
    prev = float(np.mean(counts[-24:-12])) if counts.size >= 24 else mean
    trend = max(0.0, recent - prev)

    score = 0.15
    score += min(0.5, np.tanh(mean / 5.0) * 0.35)
    score += min(0.3, np.tanh(p95 / 10.0) * 0.25)
    score += min(0.2, np.tanh(last / 10.0) * 0.2)
    score += min(0.2, np.tanh(trend / 3.0) * 0.2)
    return float(min(1.0, max(0.0, score)))


def _risk_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


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


class PredictStreamHandler(AsyncCallbackHandler):
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self.session_id = str(uuid.uuid4())
        self.step_counter = 0
        self.current_workflow_stage = "thinking"
        self.current_step_id: str | None = None

    def _next_step_id(self) -> str:
        self.step_counter += 1
        return f"step-{self.step_counter}"

    async def _send_event(self, event_type: str, data: dict, workflow_stage: str | None = None):
        payload = {
            "event": event_type,
            "event_type": event_type,
            "workflow_stage": workflow_stage or self.current_workflow_stage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
        }
        payload.update(data)
        await self.queue.put(payload)

    async def on_llm_start(self, serialized, prompts, **kwargs):
        self.current_workflow_stage = "thinking"
        self.current_step_id = self._next_step_id()
        prompt = prompts[0] if prompts else ""
        model_name = None
        if isinstance(serialized, dict):
            model_name = serialized.get("kwargs", {}).get("model_name") or serialized.get("model_name") or serialized.get("model")
        await self._send_event(
            "llm_start",
            {
                "prompt": prompt,
                "step_id": self.current_step_id,
                "model": model_name or "unknown",
            },
        )

    async def on_llm_new_token(self, token: str, **kwargs):
        await self._send_event(
            "llm_token",
            {
                "token": token,
                "step_id": self.current_step_id,
            },
        )

    async def on_llm_end(self, response, **kwargs):
        text = ""
        try:
            generations = getattr(response, "generations", None)
            if generations:
                first = generations[0][0]
                value = getattr(first, "text", None) or getattr(first, "message", None)
                if value is not None:
                    text = str(value)
        except Exception:
            text = ""
        await self._send_event(
            "llm_end",
            {
                "response": text,
                "step_id": self.current_step_id,
            },
        )

    async def on_agent_action(self, action, **kwargs):
        tool = getattr(action, "tool", "") or ""
        tool_input = getattr(action, "tool_input", None)
        log = getattr(action, "log", None)
        thought = str(log) if log else None
        if thought:
            self.current_workflow_stage = "planning"
            self.current_step_id = self._next_step_id()
            await self._send_event(
                "agent_thought",
                {
                    "thought": thought,
                    "step_id": self.current_step_id,
                },
            )
        self.current_workflow_stage = "executing"
        if not self.current_step_id:
            self.current_step_id = self._next_step_id()
        await self._send_event(
            "agent_action",
            {
                "tool": str(tool),
                "tool_input": _stringify(tool_input),
                "log": str(log) if log else None,
                "step_id": self.current_step_id,
            },
        )

    async def on_tool_start(self, serialized, input_str, **kwargs):
        name = None
        if isinstance(serialized, dict):
            name = serialized.get("name") or serialized.get("tool")
        if not name:
            name = str(serialized)
        if name == "trace_note":
            self.current_workflow_stage = "planning"
            if not self.current_step_id:
                self.current_step_id = self._next_step_id()
            await self._send_event(
                "trace_note",
                {
                    "note": _stringify(input_str),
                    "step_id": self.current_step_id,
                },
            )
            return
        self.current_workflow_stage = "executing"
        self.current_step_id = self._next_step_id()
        await self._send_event(
            "tool_start",
            {
                "tool": name,
                "tool_input": _stringify(input_str),
                "step_id": self.current_step_id,
            },
        )

    async def on_tool_end(self, output, **kwargs):
        self.current_workflow_stage = "observing"
        observation = _stringify(output)
        await self._send_event(
            "tool_end",
            {
                "observation": observation,
                "step_id": self.current_step_id,
            },
        )
        await self._send_event(
            "agent_observation",
            {
                "observation": observation,
                "step_id": self.current_step_id,
            },
        )

    async def on_chain_error(self, error, **kwargs):
        await self._send_event(
            "error",
            {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "step_id": self.current_step_id,
            },
        )


logger = logging.getLogger(__name__)


async def _run_predict(req: PredictRequest, callbacks: list | None = None) -> PredictResponse:
    logger.info("predict _run_predict start service=%s lookback_hours=%s", req.service_name, req.lookback_hours)
    llm = get_llm(streaming=callbacks is not None)
    tools = build_tools(loki)
    memory = get_memory(req.session_id)
    executor = build_executor(llm, tools, memory)

    agent_input = (
        f"服务：{req.service_name}\n"
        f"回看小时数：{req.lookback_hours}\n\n"
        "请按以下步骤执行（可在必要时多次调用 prometheus_query_range 和 predict_collect_features）：\n"
        "1) 使用 prometheus_query_range 分析该服务在回看窗口内的请求量、错误率、P95/P99 延迟以及关键业务指标走势；\n"
        "2) 调用 predict_collect_features 获取该服务在 Loki 中的错误日志计数时间序列和代表性错误日志样本；\n"
        "3) 结合指标与日志，从“是否存在明显上升趋势、新型错误模式、资源或依赖不稳定”等角度，主观评估未来一段时间的故障风险；\n"
        "4) 给出未来可能发生的若干故障类型，以及简要中文解释（面向工程师）。\n\n"
        "输出必须是JSON对象，字段为：risk_score, risk_level, likely_failures, explanation。\n"
        "其中 risk_score 为 0.0~1.0 之间的小数，用于表示你对未来发生严重故障的主观概率判断；\n"
        "risk_level 为字符串，例如 low、medium、high，需要与 risk_score 的高低相匹配。"
    )
    config = {"callbacks": callbacks} if callbacks else None
    res = await executor.ainvoke({"input": agent_input}, config=config)
    if not isinstance(res, dict):
        res = {"output": res}
    raw = str(res.get("output") or "")
    intermediate_steps = res.get("intermediate_steps") or []
    trace = _build_trace(intermediate_steps)

    features: dict | None = None
    for pair in intermediate_steps:
        try:
            action, observation = pair
        except Exception:
            continue
        tool_name = getattr(action, "tool", None)
        if tool_name == "predict_collect_features":
            if isinstance(observation, dict):
                features = observation
            else:
                try:
                    import json

                    features = json.loads(str(observation))
                except Exception:
                    features = None
            break

    counts = np.array((features or {}).get("counts") or [], dtype=float)
    logs = (features or {}).get("logs") or []

    try:
        out = LikelyFailures.model_validate_json(raw)
    except Exception:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个SRE预测助手。你只输出符合JSON schema的内容，不要输出多余文本。"),
                (
                    "human",
                    "服务：{service}\n过去{hours}小时的错误计数时间序列（5m窗口）：{counts}\n"
                    "最近的错误日志样本（可能为空/截断）：\n{logs}\n\n"
                    "请输出：一个JSON对象，其中包含：\n"
                    "1) risk_score：0.0~1.0 之间的小数，表示你对未来发生严重故障的主观概率判断；\n"
                    "2) risk_level：风险等级字符串，例如 low、medium、high；\n"
                    "3) likely_failures：未来可能出现的故障类型列表（最多6条）；\n"
                    "4) explanation：一句话中文解释（面向工程师，说明主要依据）。",
                ),
            ]
        )
        chain = prompt | llm.with_structured_output(LikelyFailures)
        logs_text = "\n".join(logs)
        out = await chain.ainvoke(
            {
                "service": req.service_name,
                "hours": req.lookback_hours,
                "counts": counts[-48:].tolist(),
                "logs": logs_text,
            },
            config=config,
        )

    score = out.risk_score
    if score is None:
        score = _risk_from_counts(counts)
    try:
        score_f = float(score)
    except Exception:
        score_f = _risk_from_counts(counts)
    if score_f < 0.0:
        score_f = 0.0
    if score_f > 1.0:
        score_f = 1.0
    level = out.risk_level or _risk_level(score_f)
    explanation = out.explanation or "基于历史错误日志密度与趋势进行粗略风险估计。"
    return PredictResponse(
        service_name=req.service_name,
        risk_score=round(score_f, 3),
        risk_level=level,
        likely_failures=out.likely_failures or [],
        explanation=explanation,
        trace=trace,
    )


@app.post("/api/predict/run", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    timeout_s = settings.request_timeout_s + 60.0
    try:
        return await asyncio.wait_for(_run_predict(req), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.error(
            "predict /api/predict/run timeout service=%s lookback_hours=%s timeout_s=%s",
            req.service_name,
            req.lookback_hours,
            timeout_s,
        )
        raise HTTPException(
            status_code=504,
            detail="预测任务超时，请检查 Prometheus/Loki/LLM 可用性后重试。",
        )


@app.post("/api/predict/run/stream")
async def predict_stream(req: PredictRequest):
    queue: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            handler = PredictStreamHandler(queue)
            await queue.put(
                {
                    "event": "start",
                    "service_name": req.service_name,
                    "lookback_hours": req.lookback_hours,
                }
            )
            try:
                timeout_s = settings.request_timeout_s + 60.0
                res = await asyncio.wait_for(_run_predict(req, callbacks=[handler]), timeout=timeout_s)
            except asyncio.TimeoutError:
                await queue.put(
                    {
                        "event": "error",
                        "message": "预测任务超时，请检查 Prometheus/Loki/LLM 可用性后重试。",
                    }
                )
                return
            meta = {
                "event": "final",
                "service_name": res.service_name,
                "risk_score": res.risk_score,
                "risk_level": res.risk_level,
                "likely_failures": res.likely_failures,
                "explanation": res.explanation,
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
