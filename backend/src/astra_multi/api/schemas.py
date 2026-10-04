"""Pydantic schemas for the Astra Multi FastAPI interface (P5.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, description="Goal of the architecture design task")
    requirements: list[str] = Field(min_length=1, description="List of requirement statements")
    mode: Literal["greenfield", "repo"] = "greenfield"
    snapshot_path: str | None = None
    idempotency_key: str | None = None
    max_rounds: int = Field(default=2, ge=1, le=10)
    token_limit: int = Field(default=0, ge=0)
    cost_limit: float = Field(default=0.0, ge=0.0)
    call_limit: int = Field(default=0, ge=0)


class RunSummaryResponse(BaseModel):
    run_id: str
    goal: str
    phase: str
    status: str
    revision: int
    created_at: str
    stop_reason: str | None = None


class RunDetailResponse(BaseModel):
    run_id: str
    task_id: str
    task_revision: int
    goal: str
    requirements: list[dict[str, Any]]
    phase: str
    status: str
    revision: int
    created_at: str
    stop_reason: str | None = None
    plan_revision: int | None = None
    plans_count: int
    issues_count: int
    blocking_issues_count: int
    decisions_count: int
    evidence_count: int
    pending_questions: list[dict[str, Any]]


class AnswerQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)


class CancelRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "User cancelled run via API"


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
