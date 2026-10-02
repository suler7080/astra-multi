"""Fake model adapter for P0 spike.

Returns deterministic outputs based on fixtures. No API key needed.
Contract: generate(role, messages, output_schema, tool_specs, limits) -> ModelResult
"""

from __future__ import annotations

from typing import Any

from astra_multi.schemas import (
    Decision,
    IndependentAnalysis,
    Issue,
    IssueSeverity,
    IssueStatus,
    ModelResult,
    PlanRevision,
    PlanStep,
    Proposal,
)

# ---------------------------------------------------------------------------
# Fixture data – deterministic per role/phase
# ---------------------------------------------------------------------------

_PLANNER_ANALYSIS = IndependentAnalysis(
    role="planner",
    findings=[
        "Codebase uses FastAPI with SQLAlchemy ORM",
        "No existing migration system detected",
        "Test coverage at ~60%",
    ],
    risks=["Migration may break existing API contracts"],
    assumptions=["PostgreSQL is the target database"],
    marker="PLANNER_MARKER_P0_SPIKE",
)

_REVIEWER_ANALYSIS = IndependentAnalysis(
    role="reviewer",
    findings=[
        "Dependency versions are outdated (SQLAlchemy 1.4)",
        "No integration tests for database layer",
        "API schema validation is inconsistent",
    ],
    risks=["Upgrading ORM may require rewriting queries"],
    assumptions=["Team has access to staging environment"],
    marker="REVIEWER_MARKER_P0_SPIKE",
)

_PLANNER_PROPOSAL = Proposal(
    id="PROP-001",
    run_id="RUN-SPIKE",
    base_revision=0,
    author_role="planner",
    approach="Incremental migration using Alembic with expand-contract pattern",
    alternatives=["Big-bang migration", "Dual-write with shadow reads"],
    requirement_coverage={
        "REQ-001": "Alembic handles schema versioning",
        "REQ-002": "Expand-contract ensures backward compatibility",
    },
)

_REVIEWER_ISSUES = [
    Issue(
        id="ISSUE-001",
        run_id="RUN-SPIKE",
        based_on_revision=0,
        severity=IssueSeverity.BLOCKING,
        status=IssueStatus.OPEN,
        claim="Proposal does not address data backfill for existing records",
        impact="Existing records could become inaccessible",
        verification_request="Verify REQ-002 data backfill coverage",
        suggested_resolution="Add backfill step between expand and contract phases",
        requirement_ids=["REQ-002"],
    ),
    Issue(
        id="ISSUE-002",
        run_id="RUN-SPIKE",
        based_on_revision=0,
        severity=IssueSeverity.WARNING,
        status=IssueStatus.OPEN,
        claim="No rollback plan specified",
        impact="A failed migration may not be reversible",
        verification_request="Verify rollback steps",
        suggested_resolution="Include reversible migration steps",
        requirement_ids=["REQ-001"],
    ),
]

_REVISED_PLAN = PlanRevision(
    id="PLAN-001",
    run_id="RUN-SPIKE",
    revision=1,
    based_on_revision=0,
    requirements_revision=1,
    snapshot_id=None,
    steps=[
        PlanStep(
            id="STEP-001",
            completion_criteria=["Alembic configuration is valid"],
            objective="Set up Alembic with expand-contract configuration",
            requirement_ids=["REQ-001"],
            dependencies=[],
            validation="alembic init succeeds; config points to correct DB",
            deliverables=["alembic.ini", "migrations/env.py"],
        ),
        PlanStep(
            id="STEP-002",
            completion_criteria=["Both schemas are accessible"],
            objective="Create expand migration with new schema alongside old",
            requirement_ids=["REQ-001", "REQ-002"],
            dependencies=["STEP-001"],
            validation="Both old and new schemas accessible; API tests pass",
            deliverables=["migrations/versions/001_expand.py"],
        ),
        PlanStep(
            id="STEP-003",
            completion_criteria=["Existing records remain accessible"],
            objective="Backfill existing records to new schema",
            requirement_ids=["REQ-002"],
            dependencies=["STEP-002"],
            validation="All existing records accessible via new schema",
            deliverables=["migrations/versions/002_backfill.py"],
        ),
        PlanStep(
            id="STEP-004",
            completion_criteria=["Rollback and compatibility tests pass"],
            objective="Contract: remove old schema after verification",
            requirement_ids=["REQ-001"],
            dependencies=["STEP-003"],
            validation="Old schema removed; all tests pass; rollback tested",
            deliverables=["migrations/versions/003_contract.py"],
        ),
    ],
    decisions=[
        Decision(
            id="DEC-001",
            run_id="RUN-SPIKE",
            question="Migration strategy",
            chosen="Expand-contract with backfill",
            rationale="Ensures zero-downtime and backward compatibility",
            alternatives=["Big-bang", "Dual-write"],
        ),
    ],
    risks=["Backfill may be slow on large tables"],
    issues_addressed=["ISSUE-001", "ISSUE-002"],
)


def generate(
    role: str,
    messages: list[dict[str, str]],
    output_schema: type | None = None,
    tool_specs: list[Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ModelResult:
    """Fake model adapter. Returns deterministic fixtures based on role."""
    # Determine what to return based on role and context
    last_msg = messages[-1]["content"] if messages else ""

    if role == "planner" and "analyze" in last_msg.lower():
        return ModelResult(content=_PLANNER_ANALYSIS, model_id="fake-planner")
    elif role == "reviewer" and "analyze" in last_msg.lower():
        return ModelResult(content=_REVIEWER_ANALYSIS, model_id="fake-reviewer")
    elif role == "planner" and "propose" in last_msg.lower():
        return ModelResult(content=_PLANNER_PROPOSAL, model_id="fake-planner")
    elif role == "reviewer" and "review" in last_msg.lower():
        return ModelResult(content=_REVIEWER_ISSUES, model_id="fake-reviewer")
    elif role == "synthesizer":
        return ModelResult(content=_REVISED_PLAN, model_id="fake-synthesizer")
    else:
        # Default: return analysis for the role
        if role == "planner":
            return ModelResult(content=_PLANNER_ANALYSIS, model_id="fake-planner")
        else:
            return ModelResult(content=_REVIEWER_ANALYSIS, model_id="fake-reviewer")
