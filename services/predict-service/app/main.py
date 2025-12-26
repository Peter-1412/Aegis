from __future__ import annotations

from datetime import datetime, timezone
import json

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.prompts import ChatPromptTemplate

from .llm import get_llm
from .loki_client import LokiClient
from .models import AgentTrace, LikelyFailures, PredictRequest, PredictResponse, TraceStep
from .settings import settings
from .agent.executor import build_executor
from .memory.store import get_memory
from .tools.predict import build_tools


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


@app.post("/api/predict/run", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    llm = get_llm()
    tools = build_tools(loki)
    memory = get_memory(req.session_id)
    executor = build_executor(llm, tools, memory)

    agent_input = (
        f"服务：{req.service_name}\n"
        f"回看小时数：{req.lookback_hours}\n\n"
        "请按以下步骤执行：\n"
        "1) 调用工具predict_collect_features获取错误计数与日志样本\n"
        "2) 基于结果输出预测\n\n"
        "输出必须是JSON对象，字段为：likely_failures, explanation。"
    )
    res = await executor.ainvoke({"input": agent_input})
    raw = str(res.get("output") or "")
    trace = _build_trace(res.get("intermediate_steps"))

    features: dict | None = None
    for action, observation in res.get("intermediate_steps") or []:
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
    score = _risk_from_counts(counts)
    level = _risk_level(score)

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
                    "请输出：可能出现的故障类型列表（最多6条）和一句话解释（面向工程师）。",
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
            }
        )

    explanation = out.explanation or "基于历史错误日志密度与趋势进行粗略风险估计。"
    return PredictResponse(
        service_name=req.service_name,
        risk_score=round(score, 3),
        risk_level=level,
        likely_failures=out.likely_failures or [],
        explanation=explanation,
        trace=trace,
    )
