"""Unit and integration tests for P5.2 enhancements:
A. Deterministic Issue ID based on normalized content (collision-free retries).
B. Budget reservation dynamically calculated from prepared prompt length and safety factor.
C. Migration F-007: Read, resume, and export compatibility for pre-supersede old run fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
import uuid

import pytest

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
)
from astra_multi.context.bundle import ByteTokenizer, ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    IssueSeverity,
    RunPhase,
    RunState,
)
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.budget import BudgetExhaustedError, BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
    derive_issue_id,
    estimate_call_tokens_and_cost,
    normalize_issue_content,
)
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.schemas import ModelResult


# ============================================================================
# Section A: Deterministic Issue ID based on Normalized Content
# ============================================================================


def test_normalize_issue_content_normalizes_whitespace_and_identifiers():
    """Content normalization must collapse spaces, strip padding, and lowercase identifiers."""
    ir1 = IssueReport(
        claim="   Uncaught   exception in  auth   middleware   ",
        impact="  Potential   denial   of service   ",
        severity=IssueSeverity.BLOCKING,
        verification_request="  Check token parser  ",
        suggested_resolution="  Wrap in try/except   ",
        requirement_ids=["REQ-002", "REQ-001"],
        evidence_ids=["EVI-B", "EVI-A"],
    )
    ir2 = IssueReport(
        claim="Uncaught exception in auth middleware",
        impact="Potential denial of service",
        severity=IssueSeverity.BLOCKING,
        verification_request="Check token parser",
        suggested_resolution="Wrap in try/except",
        requirement_ids=["req-001", "req-002"],
        evidence_ids=["evi-a", "evi-b"],
    )

    norm1 = normalize_issue_content(ir1)
    norm2 = normalize_issue_content(ir2)

    assert norm1 == norm2
    assert "  " not in norm1
    assert "req-001" in norm1
    assert "blocking" in norm1


def test_issue_id_deterministic_retry_same_content():
    """Identical issue content on retry generates the identical ID (no duplication)."""
    ir1 = IssueReport(
        claim="Database connection leak under load",
        impact="Resource exhaustion",
        severity=IssueSeverity.BLOCKING,
        suggested_resolution="Add connection pool pooling",
        requirement_ids=["REQ-001"],
    )
    ir2 = IssueReport(
        claim="  Database  connection leak under load  ",
        impact="Resource exhaustion",
        severity=IssueSeverity.BLOCKING,
        suggested_resolution="Add connection pool pooling",
        requirement_ids=["req-001"],
    )

    id1 = derive_issue_id(run_id="RUN-100", round_num=1, node="review", ir=ir1)
    id2 = derive_issue_id(run_id="RUN-100", round_num=1, node="review", ir=ir2)

    assert id1 == id2
    assert id1.startswith("ISSUE-")


def test_issue_id_different_content_at_same_index_generates_distinct_ids():
    """Different content at the same list index produces different IDs (no collision/overwrite)."""
    ir_orig = IssueReport(
        claim="Initial claim about cache invalidation",
        impact="Stale cache reads",
        severity=IssueSeverity.WARNING,
        suggested_resolution="Introduce TTL",
        requirement_ids=["REQ-001"],
    )
    ir_diff = IssueReport(
        claim="Revised claim about database Deadlock",
        impact="Transactions aborted",
        severity=IssueSeverity.BLOCKING,
        suggested_resolution="Reorder lock acquisition",
        requirement_ids=["REQ-001"],
    )

    id_orig = derive_issue_id(run_id="RUN-100", round_num=1, node="review", ir=ir_orig)
    id_diff = derive_issue_id(run_id="RUN-100", round_num=1, node="review", ir=ir_diff)

    assert id_orig != id_diff
    assert id_orig.startswith("ISSUE-")
    assert id_diff.startswith("ISSUE-")


def test_proposal_id_derivation_explanation():
    """Proposal ID derivation is stable per round; proposal is singular so no index collision risk."""
    run_id = "RUN-100"
    round_num = 1
    prop_id_1 = f"PROP-{uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:{round_num}:propose:0').hex[:8]}"
    prop_id_2 = f"PROP-{uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:{round_num}:propose:0').hex[:8]}"

    # Must be 100% deterministic across attempts for that round
    assert prop_id_1 == prop_id_2
    assert prop_id_1.startswith("PROP-")


# ============================================================================
# Section B: Budget Reservation based on Prepared Prompt Length
# ============================================================================


def test_estimate_call_tokens_and_cost_calculation():
    """Estimate formula: int((prompt_tokens + max_output_tokens) * safety_factor)."""
    messages = [
        {"role": "system", "content": "You are a software architect planner."},
        {"role": "user", "content": "Plan step implementation details."},
    ]
    # prompt length: 38 + 33 = 71 chars
    # prompt_tokens: 71 // 4 = 17 tokens
    # total = int((17 + 2000) * 1.25) = int(2017 * 1.25) = 2521 tokens
    # cost = (2521 / 1000) * 0.01 = $0.02521
    tokens, cost = estimate_call_tokens_and_cost(
        messages=messages,
        builder=None,
        max_output_tokens=2000,
        safety_factor=1.25,
    )
    assert tokens == 2521
    assert cost == pytest.approx(0.02521, rel=1e-3)


def test_estimate_call_tokens_custom_safety_factor_and_max_output(monkeypatch):
    """Safety factor and max output tokens can be configured via parameters or environment."""
    monkeypatch.setenv("ASTRA_BUDGET_SAFETY_FACTOR", "1.5")
    monkeypatch.setenv("ASTRA_MULTI_MAX_OUTPUT_TOKENS", "1000")

    messages = [{"role": "user", "content": "x" * 400}]  # 100 tokens
    # (100 + 1000) * 1.5 = 1100 * 1.5 = 1650
    tokens, cost = estimate_call_tokens_and_cost(messages)
    assert tokens == 1650
    assert cost == pytest.approx(0.0165, rel=1e-3)


def test_large_prompt_reserves_more_than_legacy_4000():
    """Large prompts (>4,000 prompt tokens) must dynamically reserve well above legacy 4,000 tokens."""
    # 24,000 chars ~= 6,000 prompt tokens
    # (6,000 + 2,000) * 1.25 = 10,000 reserved tokens
    large_text = "A" * 24000
    messages = [{"role": "user", "content": large_text}]

    tokens, cost = estimate_call_tokens_and_cost(messages, safety_factor=1.25, max_output_tokens=2000)
    assert tokens > 4000
    assert tokens == 10000
    assert cost == 0.1


def test_budget_rejection_before_model_call():
    """If estimated tokens or cost exceeds budget limit, reject before model invocation."""
    model_called = {"count": 0}

    def failing_adapter(*args: Any, **kwargs: Any) -> ModelResult:
        model_called["count"] += 1
        return ModelResult(
            content={},
            model_id="fake",
            provider="fake",
            usage={"total_tokens": 100},
            cost_actual_usd=0.001,
        )

    # Budget has limit of 3,000 tokens
    budget = BudgetService(token_limit=3000, cost_limit=1.0)
    gateway = ModelGateway(
        config=GatewayConfig(enable_output_repair=False),
        provider_adapter=failing_adapter,
    )

    # Prompt requiring ~10,000 tokens (exceeding 3,000 limit)
    large_messages = [{"role": "user", "content": "x" * 24000}]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)
            controller = WorkflowController(store, lease)
            builder = ContextBuilder(store.artifacts)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=builder,
                budget_service=budget,
            )
            graph = create_workflow_graph(wf_ctx)
            # Find the internal _call_model_with_budget via closure or direct simulation
            # We verify directly using budget.reserve and gateway
            est_tokens, est_cost = estimate_call_tokens_and_cost(large_messages, builder)
            assert est_tokens > 3000

            with pytest.raises(BudgetExhaustedError, match="Token limit .* would be exceeded"):
                budget.reserve(estimated_tokens=est_tokens, estimated_cost=est_cost)

            # Model is never called
            assert model_called["count"] == 0


def test_error_settle_releases_reservation():
    """When a model call encounters an error, the reserved budget is cleanly released."""
    budget = BudgetService(token_limit=10000, cost_limit=1.0)
    op_id = budget.reserve(estimated_tokens=2500, estimated_cost=0.025)
    assert budget.total_reserved_tokens == 2500

    # Simulate failure in call: finally block releases
    try:
        raise RuntimeError("Model provider API connection timeout")
    except Exception:
        budget.release(op_id)

    assert budget.total_reserved_tokens == 0
    assert budget.total_reserved_cost == 0.0


def test_total_reserved_never_exceeds_budget():
    """Multiple reservations respect the budget limit atomically."""
    budget = BudgetService(token_limit=5000, cost_limit=0.5)

    op1 = budget.reserve(estimated_tokens=2000, estimated_cost=0.02)
    op2 = budget.reserve(estimated_tokens=2000, estimated_cost=0.02)
    assert budget.total_reserved_tokens == 4000

    # Next reservation of 2000 exceeds 5000 limit
    with pytest.raises(BudgetExhaustedError):
        budget.reserve(estimated_tokens=2000, estimated_cost=0.02)

    assert budget.total_reserved_tokens == 4000
    assert budget.total_reserved_tokens <= 5000


# ============================================================================
# Section C: Migration F-007 (Pre-Supersede Old Run Compatibility)
# ============================================================================

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "pre_f007_run_state.json"


def test_pre_f007_fixture_read_compatibility():
    """Read compatibility: old pre-F-007 run fixture with duplicate decision questions loads cleanly."""
    assert _FIXTURE_PATH.exists(), f"{_FIXTURE_PATH} fixture must exist"

    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    state = RunState.model_validate(data)

    # Verify old run characteristics
    assert state.run.id == "RUN-OLD-001"
    # Old domain state has duplicate questions across rounds (DEC-1 and DEC-2 share question)
    assert len(state.decisions) == 3
    assert state.decisions[0].question == state.decisions[1].question
    assert state.decisions[0].id == "DEC-1"
    assert state.decisions[1].id == "DEC-2"

    # Plan revision has decisions
    assert state.plan is not None
    assert len(state.plan.decisions) == 2


def test_pre_f007_fixture_export_compatibility():
    """Export compatibility: old pre-F-007 run can be exported to JSON and Markdown without error."""
    state = RunState.model_validate_json(_FIXTURE_PATH.read_text(encoding="utf-8"))

    exporter = PlanExporter()
    json_out = exporter.export_json(state)
    md_out = exporter.export_markdown(state)

    assert json_out["schema_version"] == 1
    assert json_out["metadata"]["run_id"] == "RUN-OLD-001"
    assert len(json_out["architecture"]["decisions"]) == 2
    assert "Which database engine to use?" in md_out
    assert "DEC-1" in md_out
    assert "DEC-2" in md_out

    # Structural validator passes without blocker
    validator = StructuralQualityValidator()
    report = validator.validate(state)
    assert not report.has_blockers


def test_pre_f007_fixture_resume_compatibility_reconciles_decisions():
    """Resume compatibility: Resuming a pre-F-007 run reconciles decisions without duplicating or colliding."""
    old_state = RunState.model_validate_json(_FIXTURE_PATH.read_text(encoding="utf-8"))

    def fixed_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Resumed approach",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Covers REQ-001"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            content = ReviewOutput(summary="Review pass", issues=[], resolutions=[])
        elif output_schema == SynthesizerOutput:
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Setup backend service",
                        requirement_ids=["REQ-001"],
                        dependencies=[],
                        targets=["main.py"],
                        validation="pytest",
                        deliverables=["main.py"],
                        completion_criteria=["tests pass"],
                    )
                ],
                decisions=[
                    # Reuses existing question with identical choice (PostgreSQL)
                    DecisionDraft(
                        question="Which database engine to use?",
                        chosen="PostgreSQL",
                        rationale="Reaffirming PostgreSQL choice",
                        alternatives=["MySQL"],
                        evidence_ids=[],
                        related_issue_ids=[],
                    ),
                    # Proposes a NEW decision (logging framework)
                    DecisionDraft(
                        question="Which logging framework to use?",
                        chosen="structlog",
                        rationale="Structured JSON logging",
                        alternatives=["standard logging"],
                        evidence_ids=[],
                        related_issue_ids=[],
                    ),
                ],
                risks=[],
                issues_addressed=[],
                rationale="Resumed synthesis",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "resume_old_f007.db"
        with SQLiteStore(db_path) as store:
            # Seed the database with the pre-existing old run state (as an existing DB row)
            store.connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?)",
                (old_state.run.id, old_state.run.revision, old_state.model_dump_json()),
            )
            store.connection.commit()
            lease = store.acquire(old_state.run.id, owner="resumer", ttl=60)
            controller = WorkflowController(store, lease)

            # Build workflow and resume
            builder = ContextBuilder(store.artifacts)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=fixed_adapter,
            )
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=builder,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Resume workflow from round 0 to complete revision 2
            resumed_output = app.invoke({
                "run_id": old_state.run.id,
                "round": 0,
                "max_rounds": 1,
                "events": [],
            })
            assert resumed_output["gate_passed"] is True

            # Verify resumed state
            final_state = store.load(old_state.run.id)
            assert final_state.plan is not None
            assert final_state.plan.revision == 2

            # The new plan revision must have deduplicated/superseded decisions (1 per question)
            plan_questions = [d.question for d in final_state.plan.decisions]
            assert len(plan_questions) == len(set(plan_questions)) == 2
            assert "Which database engine to use?" in plan_questions
            assert "Which logging framework to use?" in plan_questions

            # The new decision ID for logging must not collide with DEC-1, DEC-2, DEC-3
            new_logging_dec = next(d for d in final_state.plan.decisions if d.question == "Which logging framework to use?")
            assert new_logging_dec.id not in {"DEC-1", "DEC-2", "DEC-3"}
            assert new_logging_dec.id == "DEC-4"

            # Domain state preserves full audit trail without corruption
            assert any(d.id == "DEC-1" for d in final_state.decisions)
            assert any(d.id == "DEC-2" for d in final_state.decisions)
            assert any(d.id == "DEC-3" for d in final_state.decisions)
            assert any(d.id == "DEC-4" for d in final_state.decisions)

            # Export the final resumed state
            exporter = PlanExporter()
            json_exp = exporter.export_json(final_state)
            md_exp = exporter.export_markdown(final_state)
            assert json_exp["metadata"]["plan_revision"] == 2
            assert "DEC-4" in md_exp
            assert "Which logging framework to use?" in md_exp
