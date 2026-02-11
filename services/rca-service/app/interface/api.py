from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import contextvars
import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import BaseModel
 
from app.agent.ops_agent import OpsAgent, ensure_cst
from app.interface.feishu_client import feishu_client
from app.models import OpsRequest, OpsResponse, TimeRange
from config.config import settings


_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = _request_id_var.get()
        except Exception:
            record.request_id = None
        return True


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "ops-service",
            "request_id": getattr(record, "request_id", None),
            "msg": record.getMessage(),
        }
        try:
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
        except Exception:
            pass
        return json.dumps(payload, ensure_ascii=False)


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


_root = logging.getLogger()
_root.setLevel(logging.INFO)
_json_formatter = _JSONFormatter()
_has_handler = False
for _handler in _root.handlers:
    _handler.setFormatter(_json_formatter)
    _handler.addFilter(_RequestIdFilter())
    _has_handler = True
if not _has_handler:
    _handler = logging.StreamHandler()
    _handler.setFormatter(_json_formatter)
    _handler.addFilter(_RequestIdFilter())
    _root.addHandler(_handler)

logging.getLogger("uvicorn.access").addFilter(_HealthzAccessFilter())


app = FastAPI(title="Ops Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
ops_agent = OpsAgent()


@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = _request_id_var.set(req_id)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = req_id
        return response
    finally:
        _request_id_var.reset(token)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _sanitize_feishu_text(text: str) -> str:
    parts: list[str] = []
    for token in text.split():
        if token.startswith("@_user_"):
            continue
        parts.append(token)
    return " ".join(parts).strip()


class FeishuIncoming(BaseModel):
    chat_id: str
    text: str


async def _handle_feishu_text(chat_id: str, text: str):
    raw_text = text.strip()
    if not raw_text:
        return
    text = _sanitize_feishu_text(raw_text)
    now = datetime.now(timezone(timedelta(hours=8)))
    logging.info("feishu request received, chat_id=%s, text=%s", chat_id, text)
    ack_text = "收到，我来帮您查询，预计需要 1~3 分钟，我会在之后把结果发给您。"
    try:
        logging.info("sending feishu ack, chat_id=%s, length=%s", chat_id, len(ack_text))
        await feishu_client.send_text_message(chat_id=chat_id, text=ack_text)
    except Exception as exc:
        logging.exception("send feishu ack failed: %s", exc)
    req = OpsRequest(
        description=text,
        time_range=TimeRange(start=now - timedelta(minutes=15), end=now),
        session_id=chat_id,
    )
    logging.info(
        "start ops for chat_id=%s, window=%s~%s",
        chat_id,
        (now - timedelta(minutes=15)).isoformat(),
        now.isoformat(),
    )
    t0 = time.monotonic()
    try:
        res = await ops_agent.analyze(req)
    except Exception as exc:
        logging.exception("ops failed for feishu, chat_id=%s, error=%s", chat_id, exc)
        error_text = "抱歉，分析过程中出现错误，请稍后重试或联系平台同学查看日志。"
        try:
            await feishu_client.send_text_message(chat_id=chat_id, text=error_text)
        except Exception as send_exc:
            logging.exception("send feishu error message failed: %s", send_exc)
        raise
    dt = time.monotonic() - t0
    logging.info(
        "ops finished, chat_id=%s, duration_s=%.3f, summary_len=%s",
        chat_id,
        dt,
        len(res.summary or ""),
    )
    lines: list[str] = []
    lines.append("【分析结果】")
    lines.append(f"问题：{text}")
    lines.append(f"结论：{res.summary}")
    if res.ranked_root_causes:
        lines.append("可能原因：")
        for c in res.ranked_root_causes[:3]:
            prob = f"，概率≈{c.probability:.2f}" if c.probability is not None else ""
            svc = f"（服务：{c.service}）" if c.service else ""
            lines.append(f"{c.rank}. {c.description}{svc}{prob}")
    if res.next_actions:
        lines.append("后续建议：")
        for idx, act in enumerate(res.next_actions, start=1):
            lines.append(f"{idx}. {act}")
    text_msg = "\n".join(lines)
    logging.info("sending feishu message, chat_id=%s, length=%s", chat_id, len(text_msg))
    await feishu_client.send_text_message(chat_id=chat_id, text=text_msg)


@app.post("/feishu/receive")
async def feishu_receive(payload: FeishuIncoming) -> dict[str, str]:
    await _handle_feishu_text(payload.chat_id, payload.text)
    return {"status": "ok"}


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


class OpsStreamHandler(AsyncCallbackHandler):
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


@app.post("/api/ops/analyze", response_model=OpsResponse)
async def analyze(req: OpsRequest) -> OpsResponse:
    try:
        t0 = time.monotonic()
        res = await ops_agent.analyze(req)
        dt = time.monotonic() - t0
        logging.info(
            "ops analyze api done, duration_s=%.3f, summary_len=%s, root_causes=%s, next_actions=%s",
            dt,
            len(res.summary or ""),
            len(res.ranked_root_causes or []),
            len(res.next_actions or []),
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ops/analyze/stream")
async def analyze_stream(req: OpsRequest):
    queue: asyncio.Queue = asyncio.Queue()
    req_id = _request_id_var.get() or str(uuid.uuid4())

    async def runner():
        try:
            token = _request_id_var.set(req_id)
            handler = OpsStreamHandler(queue)
            start = ensure_cst(req.time_range.start)
            end = ensure_cst(req.time_range.end)
            logging.info(
                "ops stream start, start=%s, end=%s, session_id=%s",
                start.isoformat(),
                end.isoformat(),
                handler.session_id,
            )
            await queue.put(
                {
                    "event": "start",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "request_id": req_id,
                }
            )
            t0 = time.monotonic()
            res = await ops_agent.analyze(req, callbacks=[handler])
            dt = time.monotonic() - t0
            meta = {
                "event": "final",
                "summary": res.summary,
                "ranked_root_causes": [c.model_dump() for c in res.ranked_root_causes],
                "next_actions": res.next_actions,
                "trace": res.trace.dict() if res.trace else None,
                "request_id": req_id,
            }
            logging.info(
                "ops stream final, duration_s=%.3f, summary_len=%s, root_causes=%s, next_actions=%s",
                dt,
                len(res.summary or ""),
                len(res.ranked_root_causes or []),
                len(res.next_actions or []),
            )
            await queue.put(meta)
        except Exception as exc:
            logging.exception("ops stream error: %s", exc)
            await queue.put({"event": "error", "message": str(exc), "request_id": req_id})
        finally:
            logging.info("ops stream end")
            try:
                _request_id_var.reset(token)
            except Exception:
                pass
            await queue.put({"event": "end", "request_id": req_id})

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
    logging.info(
        "alertmanager webhook received, status=%s, alert_count=%s",
        payload.status,
        len(alerts),
    )
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
    try:
        await feishu_client.send_text_message(chat_id=chat_id, text=text_msg)
        return {"status": "ok", "sent_to": chat_id, "alert_count": len(alerts)}
    except Exception as exc:
        logging.exception("alertmanager forward to feishu failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("unhandled exception: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
