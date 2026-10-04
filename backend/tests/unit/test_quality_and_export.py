"""Unit tests for P4 Quality Validator, Finalization Service, and Plan Exporter."""



from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
    RunStatus,
)
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
)


def test_structural_validator_passes_on_valid_plan():
    state = sample_state()
    plan = sample_plan(state)
    state = state.model_copy(update={"plans": [plan]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is True
    assert len(report.violations) == 0


def test_structural_validator_fails_on_uncovered_requirement():
    state = sample_state()
    plan = sample_plan(state)

    # Step covers nonexistent REQ-999 instead of REQ-001
    bad_step = plan.steps[0].model_copy(update={"requirement_ids": ["REQ-999"]})
    bad_plan = plan.model_copy(update={"steps": [bad_step]})
    state = state.model_copy(update={"plans": [bad_plan]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is False
    assert any(v.rule_id == "RULE-COV-001" for v in report.violations)


def test_structural_validator_fails_on_blocking_issue():
    state = sample_state()
    plan = sample_plan(state)
    issue = Issue(
        id="ISSUE-BLOCKER",
        run_id=state.run.id,
        severity=IssueSeverity.BLOCKING,
        status=IssueStatus.OPEN,
        based_on_revision=0,
        claim="Security vulnerability in health endpoint",
        impact="Unauthorized information disclosure",
        verification_request="Run security audit",
        suggested_resolution="Authenticate health checks",
        requirement_ids=["REQ-001"],
    )
    state = state.model_copy(update={"plans": [plan], "issues": [issue]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is False
    assert any(v.rule_id == "RULE-ISSUE-001" for v in report.violations)


def test_finalization_service_grants_final_when_all_pass():
    state = sample_state()
    plan = sample_plan(state)
    state = state.model_copy(update={"plans": [plan]})

    service = FinalizationService()
    assessment = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=plan.revision,
        feedback="Clean architecture, clear steps.",
        concerns=[],
    )

    decision = service.evaluate(state, assessment)
    assert decision.can_finalize is True
    assert decision.target_status == RunStatus.FINAL


def test_finalization_service_rejects_stale_review():
    state = sample_state()
    plan = sample_plan(state)
    state = state.model_copy(update={"plans": [plan]})

    service = FinalizationService()
    # Review was for revision 0 instead of current revision 1
    assessment = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=0,
        feedback="Good plan.",
        concerns=[],
    )

    decision = service.evaluate(state, assessment)
    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert "stale" in decision.reason.lower()


def test_plan_exporter_json_and_markdown_parity():
    state = sample_state()
    plan = sample_plan(state)
    state = state.model_copy(update={"plans": [plan]})

    exporter = PlanExporter()
    json_out = exporter.export_json(state)
    md_out = exporter.export_markdown(state)

    assert json_out["schema_version"] == 1
    assert json_out["metadata"]["run_id"] == state.run.id
    assert json_out["task"]["goal"] == state.task.goal
    assert len(json_out["steps"]) == len(plan.steps)

    assert state.task.goal in md_out
    assert state.run.id in md_out
    assert plan.steps[0].id in md_out
    assert plan.steps[0].objective in md_out
