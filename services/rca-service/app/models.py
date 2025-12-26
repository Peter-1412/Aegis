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


class RCARequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    time_range: TimeRange
    session_id: str | None = Field(default=None, max_length=200)


class RCAResponse(BaseModel):
    summary: str
    suspected_service: str | None = None
    root_cause: str | None = None
    evidence: list[str] = []
    suggested_actions: list[str] = []
    trace: AgentTrace | None = None


class RCAOutput(BaseModel):
    summary: str
    suspected_service: str | None = None
    root_cause: str | None = None
    evidence: list[str] = []
    suggested_actions: list[str] = []
