from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    start: datetime | None = None
    end: datetime | None = None
    last_minutes: int | None = Field(default=None, ge=1, le=24 * 60)


class ChatOpsQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    time_range: TimeRange | None = None
    session_id: str | None = Field(default=None, max_length=200)


class ChatOpsQueryResponse(BaseModel):
    answer: str
    used_logql: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    trace: AgentTrace | None = None


class QueryPlan(BaseModel):
    query_kind: Literal["instant", "range"]
    logql: str
    intent: str
    step_seconds: int | None = Field(default=None, ge=1, le=3600)
