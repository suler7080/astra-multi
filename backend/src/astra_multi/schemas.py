"""P0 runtime compatibility types; domain contracts live in domain.models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from astra_multi.domain.models import (
    Decision,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Proposal,
    Requirement,
    TaskSpec,
)

__all__ = [
    "Decision",
    "Issue",
    "IssueSeverity",
    "IssueStatus",
    "PlanRevision",
    "PlanStep",
    "Proposal",
    "Requirement",
    "TaskSpec",
    "Phase",
    "IndependentAnalysis",
    "ModelResult",
]


class Phase(str, Enum):
    INTAKE = "INTAKE"
    INDEPENDENT_ANALYSIS = "INDEPENDENT_ANALYSIS"
    PROPOSE = "PROPOSE"
    REVIEW = "REVIEW"
    REVISE = "REVISE"
    QUALITY_GATE = "QUALITY_GATE"
    EXPORT = "EXPORT"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass
class IndependentAnalysis:
    role: str
    findings: list[str]
    risks: list[str]
    assumptions: list[str]
    marker: str = ""  # For testing input isolation


@dataclass
class ModelResult:
    """Result from a model adapter call."""

    content: Any
    usage: dict[str, int | None] | None = None
    model_id: str = "fake-model"
    attempts: int | None = 1
    provider: str = "fake"
    latency_seconds: float | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    cost_estimate_usd: float | None = None
    cost_actual_usd: float | None = None
    cumulative_usage: dict[str, int | None] | None = None
    cumulative_cost_usd: float | None = None
    is_estimated: bool = False
