from __future__ import annotations

from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    index: int
    tool: str
    tool_input: str | None = None
    observation: str | None = None
    log: str | None = None


class AgentTrace(BaseModel):
    steps: list[TraceStep] = []


class PredictRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    lookback_hours: int = Field(default=24, ge=1, le=30 * 24)
    session_id: str | None = Field(default=None, max_length=200)


class PredictResponse(BaseModel):
    service_name: str
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    likely_failures: list[str] = []
    explanation: str
    trace: AgentTrace | None = None


class LikelyFailures(BaseModel):
    likely_failures: list[str] = []
    explanation: str
