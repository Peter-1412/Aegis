from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import json
from typing import AsyncIterator
import threading

import logging
import uuid

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import BaseModel

from .feishu_client import feishu_client
from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, RCAOutput, RCARequest, RCAResponse, TimeRange, TraceStep
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


app = FastAPI(title="RCA Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
loki = LokiClient(settings.loki_base_url, settings.loki_tenant_id, settings.request_timeout_s)


def _start_feishu_ws_client() -> None:
    app_id = settings.feishu_app_id
    app_secret = settings.feishu_app_secret
    if not app_id or not app_secret:
        logging.warning("Feishu app_id 或 app_secret 未配置，跳过长连接客户端启动")
        return
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_im_message)
        .build()
    )
    cli = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    cli.start()


@app.on_event("startup")
async def _on_startup() -> None:
    global _feishu_loop
    _feishu_loop = asyncio.get_running_loop()
    thread = threading.Thread(target=_start_feishu_ws_client, daemon=True)
    thread.start()


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


_feishu_loop: asyncio.AbstractEventLoop | None = None


async def _handle_feishu_text(chat_id: str, text: str):
    text = text.strip()
    if not text:
        return
    now = datetime.now(_CST)
    req = RCARequest(
        description=text,
        time_range=TimeRange(start=now - timedelta(minutes=15), end=now),
        session_id=chat_id,
    )
    res = await _run_rca(req)
    lines: list[str] = []
    lines.append("【自动RCA分析结果】")
    lines.append(f"时间范围（CST）：{(now - timedelta(minutes=15)).isoformat()} ~ {now.isoformat()}")
    lines.append(f"故障描述：{text}")
    lines.append("")
    lines.append(f"总结：{res.summary}")
    if res.ranked_root_causes:
        lines.append("")
        lines.append("可能的根因候选：")
        for c in res.ranked_root_causes[:3]:
            prob = f"，概率≈{c.probability:.2f}" if c.probability is not None else ""
            svc = f"（服务：{c.service}）" if c.service else ""
            lines.append(f"{c.rank}. {c.description}{svc}{prob}")
    if res.next_actions:
        lines.append("")
        lines.append("建议后续操作：")
        for idx, act in enumerate(res.next_actions, start=1):
            lines.append(f"{idx}. {act}")
    text_msg = "\n".join(lines)
    await feishu_client.send_text_message(chat_id=chat_id, text=text_msg)


def _on_im_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    if event is None or event.message is None:
        return
    message = event.message
    chat_id = message.chat_id or settings.feishu_default_chat_id
    if not chat_id:
        return
    content_raw = message.content or "{}"
    try:
        content_obj = json.loads(content_raw)
    except Exception:
        content_obj = {}
    text = str(content_obj.get("text") or "").strip()
    if not text:
        return
    loop = _feishu_loop
    if loop is None:
        return
    fut = asyncio.run_coroutine_threadsafe(_handle_feishu_text(chat_id, text), loop)

    def _log_result(future):
        exc = future.exception()
        if exc is not None:
            logging.exception("Feishu message handler error: %s", exc)

    fut.add_done_callback(_log_result)


class Alert(BaseModel):
    status: str | None = None
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    startsAt: datetime | None = None
    endsAt: datetime | None = None


class AlertmanagerWebhook(BaseModel):
    status: str | None = None
    receiver: str | None = None
    alerts: list[Alert] = []


class RCAStreamHandler(AsyncCallbackHandler):
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
        "请结合可用的 Prometheus/Loki/Jaeger 工具完成根因分析，并严格按照系统提示中的 JSON schema 输出结果。"
    )
    config = {"callbacks": callbacks} if callbacks else None
    res = await executor.ainvoke({"input": agent_input}, config=config)
    raw = str(res.get("output") or "")
    try:
        out = RCAOutput.model_validate_json(raw)
    except Exception:
        out = RCAOutput(summary=raw.strip() or "模型输出为空。", ranked_root_causes=[], next_actions=[])
    trace = _build_trace(res.get("intermediate_steps"))
    return RCAResponse(
        summary=out.summary,
        ranked_root_causes=out.ranked_root_causes or [],
        next_actions=out.next_actions or [],
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
                "ranked_root_causes": [c.model_dump() for c in res.ranked_root_causes],
                "next_actions": res.next_actions,
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


@app.post("/alertmanager/webhook")
async def alertmanager_webhook(payload: AlertmanagerWebhook):
    chat_id = settings.feishu_default_chat_id
    if not chat_id:
        return {"status": "ignored", "reason": "feishu_default_chat_id not configured"}

    alerts = payload.alerts or []
    if not alerts:
        return {"status": "ignored", "reason": "no alerts"}

    lines: list[str] = []
    lines.append("@所有人")
    lines.append("【Kubernetes 集群告警通知】")
    lines.append(f"Alertmanager status: {payload.status or 'unknown'}")
    lines.append(f"告警数量: {len(alerts)}")
    lines.append("")

    for idx, alert in enumerate(alerts, start=1):
        labels = alert.labels or {}
        annotations = alert.annotations or {}
        name = labels.get("alertname") or "unnamed"
        severity = labels.get("severity") or "unknown"
        instance = labels.get("instance") or labels.get("pod") or labels.get("service") or "-"
        summary = annotations.get("summary") or annotations.get("description") or ""
        lines.append(f"{idx}. [{severity}] {name} @ {instance}")
        if summary:
            lines.append(f"   概要: {summary}")

    text_msg = "\n".join(lines)
    await feishu_client.send_text_message(chat_id=chat_id, text=text_msg)

    return {"status": "ok", "sent_to": chat_id, "alert_count": len(alerts)}
