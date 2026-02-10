from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    index: int
    tool: str
    tool_input: str | None = None
    observation: str | None = None
    log: str | None = None


class AgentTrace(BaseModel):
    steps: list[TraceStep] = []


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class OpsRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    time_range: TimeRange
    session_id: str | None = Field(default=None, max_length=200)


class RootCauseCandidate(BaseModel):
    rank: int = Field(ge=1, le=10)
    service: str | None = None
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str
    key_indicators: list[str] = []
    key_logs: list[str] = []


class OpsOutput(BaseModel):
    summary: str
    ranked_root_causes: list[RootCauseCandidate] = []
    next_actions: list[str] = []


class OpsResponse(BaseModel):
    summary: str
    ranked_root_causes: list[RootCauseCandidate] = []
    next_actions: list[str] = []
    trace: AgentTrace | None = None
