from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import asyncio
from difflib import SequenceMatcher
import os
import httpx

from app.agent.executor import build_executor
from app.interface.llm import get_llm
from app.tools.loki_tool import LokiClient
from app.memory.store import get_memory
from app.models import AgentTrace, OpsOutput, OpsRequest, OpsResponse, TraceStep
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


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / float(len(a | b))


def _response_similarity(a: OpsResponse, b: OpsResponse) -> float:
    sa = (a.summary or "").strip()
    sb = (b.summary or "").strip()
    summary_sim = SequenceMatcher(None, sa, sb).ratio() if sa and sb else 0.0
    ra = {
        (c.service or "").strip().lower() + "|" + c.description.strip().lower()
        for c in (a.ranked_root_causes or [])
        if c.description
    }
    rb = {
        (c.service or "").strip().lower() + "|" + c.description.strip().lower()
        for c in (b.ranked_root_causes or [])
        if c.description
    }
    rc_sim = _jaccard(ra, rb)
    aa = {s.strip().lower() for s in (a.next_actions or []) if s}
    ab = {s.strip().lower() for s in (b.next_actions or []) if s}
    actions_sim = _jaccard(aa, ab)
    return 0.6 * summary_sim + 0.25 * rc_sim + 0.15 * actions_sim


class OpsAgent:
    def __init__(self):
        self._loki = LokiClient(settings.loki_base_url, settings.loki_tenant_id, settings.request_timeout_s)

    async def _run_with_model(
        self,
        req: OpsRequest,
        model_name: str,
        callbacks: list | None = None,
        use_memory: bool = True,
    ) -> OpsResponse:
        start = ensure_cst(req.time_range.start)
        end = ensure_cst(req.time_range.end)
        if end <= start:
            raise ValueError("end必须大于start。")
        llm = get_llm(model_name=model_name, streaming=callbacks is not None, allow_thinking=True)
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
            logging.exception("ops executor failed: %s", exc)
            raise
        t1 = datetime.now(timezone.utc)
        raw = str(res.get("output") or "")
        try:
            out = OpsOutput.model_validate_json(raw)
        except Exception:
            logging.warning("ops output parse failed, output_len=%s", len(raw))
            out = OpsOutput(summary=raw.strip() or "模型输出为空。", ranked_root_causes=[], next_actions=[])
        trace = _build_trace(res.get("intermediate_steps"))
        resp = OpsResponse(
            summary=out.summary,
            ranked_root_causes=out.ranked_root_causes or [],
            next_actions=out.next_actions or [],
            trace=trace,
            model=model_name,
        )
        logging.info(
            "ops analyze end, model=%s, duration_s=%.3f, summary_len=%s, root_causes=%s, next_actions=%s, trace_steps=%s",
            model_name,
            (t1 - t0).total_seconds(),
            len(resp.summary or ""),
            len(resp.ranked_root_causes or []),
            len(resp.next_actions or []),
            len(resp.trace.steps) if resp.trace and resp.trace.steps else 0,
        )
        return resp

    async def analyze(self, req: OpsRequest, callbacks: list | None = None) -> OpsResponse:
        logging.info(
            "ops analyze start, description_len=%s, session_id=%s, start_raw=%s, end_raw=%s, model=%s",
            len(req.description or ""),
            req.session_id,
            getattr(req.time_range, "start", None),
            getattr(req.time_range, "end", None),
            req.model or settings.default_model,
        )
        model_name = req.model or settings.default_model
        return await self._run_with_model(req, model_name, callbacks=callbacks, use_memory=True)

    async def analyze_ensemble(self, req: OpsRequest, model_names: list[str]) -> OpsResponse:
        logging.info(
            "ops analyze ensemble start, description_len=%s, session_id=%s, models=%s",
            len(req.description or ""),
            req.session_id,
            ",".join(model_names),
        )

        async def _model_available(name: str) -> bool:
            if name == "doubao":
                key = settings.doubao_api_key or os.getenv("ARK_API_KEY")
                return bool(key)
            base = settings.ollama_base_url
            if not base:
                return False
            url = f"{base.rstrip('/')}/api/tags"
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(url)
                return r.status_code < 500
            except Exception:
                return False

        avail_checks = await asyncio.gather(*[asyncio.create_task(_model_available(m)) for m in model_names])
        available_models = [m for m, ok in zip(model_names, avail_checks) if ok]
        if not available_models:
            logging.error("ops analyze ensemble: no available models, will fallback")
            available_models = []

        async def _task(name: str):
            try:
                resp = await self._run_with_model(req, name, callbacks=None, use_memory=False)
                return name, resp, None
            except Exception as exc:
                logging.exception("ops analyze ensemble failed for model=%s: %s", name, exc)
                return name, None, exc

        target_models = available_models or model_names
        tasks = [asyncio.create_task(_task(m)) for m in target_models]
        results = await asyncio.gather(*tasks)

        valid: list[tuple[str, OpsResponse]] = []
        errors: list[tuple[str, Exception]] = []
        for name, resp, exc in results:
            if resp is not None:
                valid.append((name, resp))
            elif exc is not None:
                errors.append((name, exc))

        if not valid:
            logging.error("ops analyze ensemble: all models failed for models=%s", ",".join(model_names))
            fallback_model = req.model or settings.default_model
            try:
                logging.info("ops analyze ensemble fallback start, model=%s", fallback_model)
                return await self._run_with_model(req, fallback_model, callbacks=None, use_memory=True)
            except Exception as exc:
                logging.exception(
                    "ops analyze ensemble fallback failed, model=%s, error=%s",
                    fallback_model,
                    exc,
                )
                raise

        if len(valid) == 1:
            selected_name, selected_resp = valid[0]
            logging.info("ops analyze ensemble selected model=%s (only valid)", selected_name)
            return selected_resp

        scores: dict[str, float] = {}
        for i, (name_i, resp_i) in enumerate(valid):
            total = 0.0
            count = 0
            for j, (name_j, resp_j) in enumerate(valid):
                if i == j:
                    continue
                total += _response_similarity(resp_i, resp_j)
                count += 1
            scores[name_i] = total / count if count else 0.0

        best_name = max(scores.items(), key=lambda x: x[1])[0]
        original_best = next(resp for name, resp in valid if name == best_name)
        best_resp = OpsResponse(
            summary=original_best.summary,
            ranked_root_causes=original_best.ranked_root_causes,
            next_actions=original_best.next_actions,
            trace=original_best.trace,
            model=best_name,
            ensemble_scores=scores,
        )
        logging.info(
            "ops analyze ensemble selected model=%s, score=%.3f, models_scored=%s",
            best_name,
            scores.get(best_name, 0.0),
            ",".join(f"{k}:{v:.3f}" for k, v in scores.items()),
        )
        return best_resp
