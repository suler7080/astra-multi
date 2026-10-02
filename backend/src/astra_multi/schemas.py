"""Minimal domain schemas for P0 spike.

These are spike-quality schemas to prove the orchestration concept.
They will be revisited and refined in P1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class IssueSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"


@dataclass
class Requirement:
    id: str
    text: str
    acceptance: str


@dataclass
class TaskSpec:
    id: str
    goal: str
    requirements: list[Requirement]
    constraints: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    revision: int = 1


@dataclass
class IndependentAnalysis:
    role: str
    findings: list[str]
    risks: list[str]
    assumptions: list[str]
    marker: str = ""  # For testing input isolation


@dataclass
class Proposal:
    id: str
    author_role: str
    approach: str
    alternatives: list[str]
    requirement_coverage: dict[str, str]  # req_id -> how addressed


@dataclass
class Issue:
    id: str
    severity: IssueSeverity
    status: IssueStatus
    claim: str
    evidence: str
    suggested_resolution: str
    requirement_ids: list[str] = field(default_factory=list)
    resolution: str = ""
    reviewed_revision: int | None = None


@dataclass
class Decision:
    id: str
    question: str
    chosen: str
    rationale: str
    alternatives: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    id: str
    objective: str
    requirement_ids: list[str]
    dependencies: list[str]  # step IDs
    validation: str
    deliverables: list[str]


@dataclass
class PlanRevision:
    id: str
    revision: int
    steps: list[PlanStep]
    decisions: list[Decision]
    risks: list[str]
    issues_addressed: list[str]  # issue IDs


@dataclass
class ModelResult:
    """Result from a model adapter call."""
    content: Any
    usage: dict[str, int] | None = None
    model_id: str = "fake-model"
    attempts: int = 1
