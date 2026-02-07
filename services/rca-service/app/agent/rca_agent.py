from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging

from app.agent.executor import build_executor
from app.interface.llm import get_llm
from app.tools.loki_tool import LokiClient
from app.memory.store import get_memory
from app.models import AgentTrace, RCAOutput, RCARequest, RCAResponse, TraceStep
from app.tools import build_tools
from config.config import settings


_CST = timezone(timedelta(hours=8))


def ensure_cst(dt: datetime) -> datetime:
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


class RcaAgent:
    def __init__(self):
        self._loki = LokiClient(settings.loki_base_url, settings.loki_tenant_id, settings.request_timeout_s)

    async def analyze(self, req: RCARequest, callbacks: list | None = None) -> RCAResponse:
        logging.info(
            "rca analyze start, description_len=%s, session_id=%s, start_raw=%s, end_raw=%s",
            len(req.description or ""),
            req.session_id,
            getattr(req.time_range, "start", None),
            getattr(req.time_range, "end", None),
        )
        start = ensure_cst(req.time_range.start)
        end = ensure_cst(req.time_range.end)
        if end <= start:
            raise ValueError("end必须大于start。")
        llm = get_llm(streaming=callbacks is not None, allow_thinking=True)
        tools = build_tools(self._loki)
        memory = get_memory(req.session_id)
        executor = build_executor(llm, tools, memory)
        agent_input = (
            f"故障描述：{req.description}\n"
            f"时间范围（CST，UTC+8）：{start.isoformat()} ~ {end.isoformat()}\n\n"
            "请结合可用的 Prometheus/Loki/Jaeger 工具完成根因分析，并严格按照系统提示中的 JSON schema 输出结果。"
        )
        config = {"callbacks": callbacks} if callbacks else None
        t0 = datetime.now(timezone.utc)
        try:
            res = await executor.ainvoke({"input": agent_input}, config=config)
        except Exception as exc:
            logging.exception("rca executor failed: %s", exc)
            raise
        t1 = datetime.now(timezone.utc)
        raw = str(res.get("output") or "")
        try:
            out = RCAOutput.model_validate_json(raw)
        except Exception:
            logging.warning("rca output parse failed, output_len=%s", len(raw))
            out = RCAOutput(summary=raw.strip() or "模型输出为空。", ranked_root_causes=[], next_actions=[])
        trace = _build_trace(res.get("intermediate_steps"))
        resp = RCAResponse(
            summary=out.summary,
            ranked_root_causes=out.ranked_root_causes or [],
            next_actions=out.next_actions or [],
            trace=trace,
        )
        logging.info(
            "rca analyze end, duration_s=%.3f, summary_len=%s, root_causes=%s, next_actions=%s, trace_steps=%s",
            (t1 - t0).total_seconds(),
            len(resp.summary or ""),
            len(resp.ranked_root_causes or []),
            len(resp.next_actions or []),
            len(resp.trace.steps) if resp.trace and resp.trace.steps else 0,
        )
        return resp
