"""Test suite for Phase 1 [B]: RULE-ISSUE-002 (open warning and blocking issues block finalization)."""

import tempfile
from pathlib import Path

from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
    RunPhase,
    RunStatus,
)
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
    ViolationSeverity,
)
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph
from astra_multi.persistence.sqlite import SQLiteStore


def test_rule_issue_002_blocks_open_warning():
    """Plan có issue WARNING ở trạng thái OPEN -> validator báo BLOCKER với rule_id 'RULE-ISSUE-002'."""
    state = sample_state()
    plan = sample_plan(state)
    warning_issue = Issue(
        id="ISSUE-WARN-1",
        run_id=state.run.id,
        severity=IssueSeverity.WARNING,
        status=IssueStatus.OPEN,
        based_on_revision=0,
        claim="Missing circuit breaker for remote calls",
        impact="Cascade failure under network timeout",
        verification_request="Verify failover behavior",
        suggested_resolution="Wrap calls in CircuitBreaker",
        requirement_ids=["REQ-001"],
    )
    state = state.model_copy(update={"plans": [plan], "issues": [warning_issue]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is False
    v2_violations = [v for v in report.violations if v.rule_id == "RULE-ISSUE-002"]
    assert len(v2_violations) == 1
    v = v2_violations[0]
    assert v.severity == ViolationSeverity.BLOCKER
    assert "ISSUE-WARN-1" in v.message
    assert "Giải quyết, từ chối hoặc đánh dấu trùng" in v.remediation


def test_rule_issue_002_passes_resolved_warning():
    """Plan có issue WARNING đã RESOLVED -> validator PASS (nếu không có lỗi khác)."""
    state = sample_state()
    plan = sample_plan(state)
    from astra_multi.domain.models import IssueResolution
    resolved_issue = Issue(
        id="ISSUE-WARN-2",
        run_id=state.run.id,
        severity=IssueSeverity.WARNING,
        status=IssueStatus.RESOLVED,
        based_on_revision=0,
        claim="Missing circuit breaker for remote calls",
        impact="Cascade failure under network timeout",
        verification_request="Verify failover behavior",
        suggested_resolution="Wrap calls in CircuitBreaker",
        resolution=IssueResolution(text="Wrapped calls in CircuitBreaker"),
        requirement_ids=["REQ-001"],
    )
    state = state.model_copy(update={"plans": [plan], "issues": [resolved_issue]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is True
    assert not any(v.rule_id == "RULE-ISSUE-002" for v in report.violations)


def test_rule_issue_002_ignores_info_issue():
    """Plan có issue INFO ở trạng thái OPEN -> validator KHÔNG báo blocker từ rule này."""
    state = sample_state()
    plan = sample_plan(state)
    info_issue = Issue(
        id="ISSUE-INFO-1",
        run_id=state.run.id,
        severity=IssueSeverity.INFO,
        status=IssueStatus.OPEN,
        based_on_revision=0,
        claim="Consider renaming helper function",
        impact="Minor readability",
        verification_request="Review naming convention",
        suggested_resolution="Rename to make clearer",
        requirement_ids=["REQ-001"],
    )
    state = state.model_copy(update={"plans": [plan], "issues": [info_issue]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is True
    assert not any(v.rule_id == "RULE-ISSUE-002" for v in report.violations)


def test_workflow_max_rounds_with_open_warning_ends_partial():
    """Chạy workflow đến max rounds với open warning -> run kết thúc PARTIAL, không phải FINAL."""
    from astra_multi.agents.roles import (
        AnalysisOutput,
        IssueReport,
        ProposalOutput,
        ReviewOutput,
        StepDraft,
        SynthesizerOutput,
    )
    from astra_multi.context.bundle import ContextBuilder
    from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
    from astra_multi.orchestration.termination import StopReason
    from astra_multi.schemas import ModelResult

    def fake_adapter(provider: str, role: str, messages: list[dict[str, str]], output_schema: type, **kwargs):
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard proposal",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            content = ReviewOutput(
                summary="Review detected warning",
                issues=[
                    IssueReport(
                        claim="Potential race condition in memory cache",
                        impact="Dirty reads under concurrent requests",
                        severity=IssueSeverity.WARNING,
                        suggested_resolution="Use thread lock",
                        requirement_ids=["REQ-001"],
                    )
                ],
                resolutions=[],
            )
        elif output_schema == SynthesizerOutput:
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Step 1 implementation",
                        requirement_ids=["REQ-001"],
                        validation="pytest",
                        deliverables=["Cache module"],
                        completion_criteria=["Thread safe"],
                    )
                ],
                decisions=[],
                risks=[],
                issues_addressed=[],  # Warning never addressed
                rationale="Draft without addressing warning",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)
            ctrl = WorkflowController(store, lease)
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=fake_adapter)
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(controller=ctrl, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            max_rounds = 1
            final_output = app.invoke({
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            })

            assert final_output["gate_passed"] is False
            assert StopReason.MAX_ROUNDS_REACHED.value in final_output["stop_reason"]

            final_state = store.load(state.run.id)
            assert final_state.run.status == RunStatus.PARTIAL
            assert final_state.run.phase == RunPhase.EXPORT
            assert "RULE-ISSUE-002" in final_state.run.stop_reason or "Potential race condition" in final_state.run.stop_reason
            assert "FINAL" not in final_state.run.status.value
