"""Risk-based escalation and human-approval tests for finalization."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from astra_multi.domain.commands import TransitionRun
from astra_multi.domain.models import (
    ExecutionStatus,
    HumanReviewApproval,
    RunPhase,
    RunState,
    RunStatus,
    WorkerExecutionRecord,
)
from astra_multi.domain.policies import InvalidState, apply_mutation
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import create_workflow_graph
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.sqlite import SQLiteStore
from tests.unit.test_phase5_finalization_gate import (
    _build_compliant_state,
    _rubric_audit,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _passing_review(**overrides) -> SemanticReviewAssessment:
    values = {
        "passed": True,
        "reviewed_plan_revision": 1,
        "feedback": "Plan satisfies all rubrics.",
        "concerns": [],
        "rubric_audits": [
            _rubric_audit("RUBRIC-TECH-001", "REQ-TECH-001"),
            _rubric_audit("RUBRIC-DELIV-001", "REQ-DELIV-001"),
            _rubric_audit("RUBRIC-ORG-001", "REQ-ORG-001"),
        ],
    }
    values.update(overrides)
    return SemanticReviewAssessment(**values)


def _approval(state) -> HumanReviewApproval:
    return HumanReviewApproval(
        id="APPROVAL-1",
        run_id=state.run.id,
        plan_revision=state.plan.revision,
        reviewer="release-manager",
        reason="Risk accepted for this plan revision",
        approved_at=NOW,
    )


def _record(
    state,
    *,
    status: ExecutionStatus = ExecutionStatus.PASSED,
    diff_passed: bool = True,
    changed_files: list[str] | None = None,
    violations: list[str] | None = None,
) -> WorkerExecutionRecord:
    return WorkerExecutionRecord(
        id="EXEC-1",
        run_id=state.run.id,
        plan_revision=state.plan.revision,
        step_id="STEP-001",
        scope_id="SCOPE-1",
        worker_role="ui",
        status=status,
        started_at=NOW,
        finished_at=NOW,
        diff_passed=diff_passed,
        changed_files=changed_files or [],
        violations=violations or [],
    )


def _with_overlap(state):
    # Both the UI and API workers now claim src/js/api.js.  The UI step also
    # uses it, so the only contract violation is cross-role overlap (006).
    state.plan.assignment_matrix.workers[0].owned_files.append("src/js/api.js")
    state.plan.steps[0].owned_files.append("src/js/api.js")
    return state


# ---------------------------------------------------------------------------
# Finalization escalation
# ---------------------------------------------------------------------------


def test_ownership_overlap_escalates_to_waiting_for_human_review():
    state = _with_overlap(_build_compliant_state())

    decision = FinalizationService().evaluate(state, _passing_review())

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert decision.pillar_results["human_review"].passed is False
    assert any(
        "Ownership contract contains cross-role overlap" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_export_node_escalates_ownership_overlap_instead_of_final():
    state = _with_overlap(_build_compliant_state())
    ctrl = MagicMock()
    ctrl.actor = "P4-quality-service"
    ctrl.get_state.return_value = state
    ctrl.get_semantic_review.return_value = _passing_review()
    wf_ctx = MagicMock(controller=ctrl, stagnation_detector=StagnationDetector())
    graph = create_workflow_graph(wf_ctx)

    graph.nodes["export"].runnable.invoke({"gate_passed": True})

    statuses = [
        call.args[1]
        for call in ctrl.transition_phase.call_args_list
        if len(call.args) >= 2
    ]
    assert statuses[-1] == RunStatus.WAITING_FOR_HUMAN_REVIEW


def test_approved_overlap_revision_can_finalize():
    state = _with_overlap(_build_compliant_state())
    state = state.model_copy(
        update={"human_review_approvals": [_approval(state)]}
    )

    decision = FinalizationService().evaluate(state, _passing_review())

    assert decision.can_finalize is True
    assert decision.target_status == RunStatus.FINAL
    assert decision.pillar_results["human_review"].passed is True
    assert "acknowledged" in decision.pillar_results["human_review"].details


def test_out_of_scope_diff_escalates_and_approval_still_blocks_final():
    state = _build_compliant_state()
    record = _record(
        state,
        status=ExecutionStatus.DENIED,
        diff_passed=False,
        changed_files=["src/outside.py"],
        violations=["WORKER_FILE_DIFF_OUT_OF_SCOPE: src/outside.py"],
    )
    state = state.model_copy(update={"execution_records": [record]})

    decision = FinalizationService().evaluate(state, _passing_review())

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert decision.pillar_results["runtime_scope"].passed is False
    assert decision.pillar_results["human_review"].passed is False
    assert any(
        "outside the declared owned_files" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )

    approved = state.model_copy(
        update={"human_review_approvals": [_approval(state)]}
    )
    decision = FinalizationService().evaluate(approved, _passing_review())

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["runtime_scope"].passed is False
    assert decision.pillar_results["human_review"].passed is True


def test_run_state_rejects_passed_but_accepts_denied_out_of_scope_records():
    state = _build_compliant_state()
    passed = _record(state, changed_files=["src/outside.py"])
    with pytest.raises(
        ValidationError, match="passed execution changed files outside step scope"
    ):
        RunState.model_validate(
            state.model_dump() | {"execution_records": [passed.model_dump()]}
        )

    denied = _record(
        state,
        status=ExecutionStatus.DENIED,
        diff_passed=False,
        changed_files=["src/outside.py"],
        violations=["WORKER_FILE_DIFF_OUT_OF_SCOPE: src/outside.py"],
    )
    validated = RunState.model_validate(
        state.model_dump() | {"execution_records": [denied.model_dump()]}
    )
    assert validated.execution_records[0].changed_files == ["src/outside.py"]


def test_execution_record_must_reference_the_executed_plan_revision():
    state = _build_compliant_state()
    record = _record(state).model_copy(update={"plan_revision": 2})

    with pytest.raises(ValidationError, match="unknown plan revision/step"):
        RunState.model_validate(
            state.model_dump() | {"execution_records": [record.model_dump()]}
        )


def test_denied_runtime_execution_escalates_to_human_review():
    state = _build_compliant_state()
    record = _record(
        state,
        status=ExecutionStatus.DENIED,
        diff_passed=False,
        violations=["WORKER_FILE_PATH_OUTSIDE_SCOPE: src/outside.py"],
    )
    state = state.model_copy(update={"execution_records": [record]})

    decision = FinalizationService().evaluate(state, _passing_review())

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "denied or failed" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_validator_reviewer_conflict_escalates_to_human_review():
    state = _build_compliant_state()
    review = _passing_review(
        validator_llm_conflicts=["REQ-TECH-001: validator says FAIL but reviewer says PASS"]
    )

    decision = FinalizationService().evaluate(state, review)

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "disagree" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_missing_evidence_escalates_to_human_review():
    state = _build_compliant_state()
    review = _passing_review(missing_evidence=["REQ-DELIV-001"])

    decision = FinalizationService().evaluate(state, review)

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "lacks machine-checkable evidence" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_semantic_partial_escalates_to_human_review():
    state = _build_compliant_state()
    review = _passing_review(
        requirement_verdicts=[
            {
                "requirement_id": "REQ-TECH-001",
                "restated": "Run via file://",
                "mechanism": "defer script",
                "verdict": "PARTIAL",
                "gap": "Needs browser verification",
            }
        ]
    )

    decision = FinalizationService().evaluate(state, review)

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "PARTIAL" in diagnostic
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_sensitive_file_escalates_to_human_review():
    state = _build_compliant_state()
    state.plan.assignment_matrix.workers[0].owned_files.append(".env")
    state.plan.steps[0].owned_files.append(".env")

    decision = FinalizationService().evaluate(state, _passing_review())

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "sensitive" in diagnostic.lower()
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


def test_plan_uncertainty_escalates_to_human_review():
    state = _build_compliant_state()
    review = _passing_review(plan_uncertainty=["Unknown browser support matrix"])

    decision = FinalizationService().evaluate(state, review)

    assert decision.target_status == RunStatus.WAITING_FOR_HUMAN_REVIEW
    assert any(
        "uncertainty" in diagnostic.lower()
        for diagnostic in decision.pillar_results["human_review"].diagnostics
    )


# ---------------------------------------------------------------------------
# Policy transitions
# ---------------------------------------------------------------------------


def _transition(status: RunStatus, *, actor: str = "P4-quality-service") -> TransitionRun:
    return TransitionRun(
        expected_revision=1,
        node="finalize",
        logical_operation_id="op-finalize",
        actor=actor,
        phase=state_phase,
        status=status,
        reason="8-pillar gate completed",
    )


state_phase = _build_compliant_state().run.phase


def test_final_from_human_review_requires_approval():
    state = _build_compliant_state()
    state = state.model_copy(
        update={
            "run": state.run.model_copy(
                update={"status": RunStatus.WAITING_FOR_HUMAN_REVIEW}
            )
        }
    )

    with pytest.raises(InvalidState, match="human review approval"):
        apply_mutation(state, _transition(RunStatus.FINAL), NOW)


def test_final_from_human_review_succeeds_with_current_revision_approval():
    state = _build_compliant_state()
    state = state.model_copy(
        update={
            "run": state.run.model_copy(
                update={"status": RunStatus.WAITING_FOR_HUMAN_REVIEW}
            )
        }
    )
    state = state.model_copy(
        update={"human_review_approvals": [_approval(state)]}
    )

    updated, _ = apply_mutation(state, _transition(RunStatus.FINAL), NOW)

    assert updated.run.status == RunStatus.FINAL
    assert updated.run.phase == state.run.phase


def test_human_review_rejection_marks_partial_without_approval():
    state = _build_compliant_state()
    state = state.model_copy(
        update={
            "run": state.run.model_copy(
                update={"status": RunStatus.WAITING_FOR_HUMAN_REVIEW}
            )
        }
    )

    updated, _ = apply_mutation(
        state, _transition(RunStatus.PARTIAL, actor="api-user"), NOW
    )

    assert updated.run.status == RunStatus.PARTIAL
    assert updated.run.phase == state.run.phase


def test_resume_from_human_review_requires_approval():
    state = _build_compliant_state()
    state = state.model_copy(
        update={
            "run": state.run.model_copy(
                update={"status": RunStatus.WAITING_FOR_HUMAN_REVIEW}
            )
        }
    )

    with pytest.raises(InvalidState, match="requires an approval"):
        apply_mutation(
            state, _transition(RunStatus.RUNNING, actor="api-user"), NOW
        )

    approved = state.model_copy(
        update={"human_review_approvals": [_approval(state)]}
    )
    updated, _ = apply_mutation(
        approved, _transition(RunStatus.RUNNING, actor="api-user"), NOW
    )
    assert updated.run.status == RunStatus.RUNNING


def test_controller_approval_is_recorded_for_current_revision_and_resumes(
    tmp_path,
):
    template = _build_compliant_state()
    store = SQLiteStore(tmp_path / "approval.db")
    try:
        run = template.run.model_copy(update={"phase": RunPhase.INTAKE})
        store.create(template.task, run)
        lease = store.acquire(run.id, owner="test", ttl=30)
        try:
            ctrl = WorkflowController(store, lease, actor="api-user")
            ctrl.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
            ctrl.transition_phase(RunPhase.PROPOSE)
            ctrl.transition_phase(RunPhase.REVIEW)
            ctrl.transition_phase(RunPhase.REVISE)
            ctrl.commit_plan_revision(template.plan)
            ctrl.transition_phase(RunPhase.QUALITY_GATE)
            ctrl.transition_phase(RunPhase.EXPORT)
            ctrl.transition_phase(
                RunPhase.EXPORT,
                RunStatus.WAITING_FOR_HUMAN_REVIEW,
                reason="risk trigger",
            )

            updated = ctrl.approve_human_review(
                reviewer="release-manager", reason="risk accepted"
            )
        finally:
            store.release(lease)
    finally:
        store.close()

    assert updated.run.status == RunStatus.RUNNING
    assert len(updated.human_review_approvals) == 1
    approval = updated.human_review_approvals[0]
    assert approval.plan_revision == updated.plan.revision
    assert approval.reviewer == "release-manager"
