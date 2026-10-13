"""Test suite for Phase 2 [F]: Semantic review phải độc lập với Synthesizer."""

import tempfile
from pathlib import Path
import pytest

from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.commands import ChangeIssue
from astra_multi.domain.models import (
    Issue,
    IssueResolution,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    utc_now,
)
from astra_multi.domain.policies import InvalidState, apply_mutation
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.roles import ROLE_GROUP
from astra_multi.orchestration.graph import WorkflowContext
from astra_multi.persistence.sqlite import SQLiteStore


def test_semantic_review_role_group_mapping_is_reviewer():
    """orchestration/roles.py must map 'semantic_review' to 'reviewer', not 'synthesizer'."""
    assert ROLE_GROUP["semantic_review"] == "reviewer"

    wf_ctx = WorkflowContext(
        controller=None,  # type: ignore
        gateway=None,  # type: ignore
        context_builder=None,  # type: ignore
        evidence_ledger=None,  # type: ignore
        budget_service=None,  # type: ignore
        role_assignments={
            "synthesizer": {"provider": "provider-synth", "model": "model-synth"},
            "reviewer": {"provider": "provider-reviewer", "model": "model-reviewer"},
        },
    )
    provider, model = wf_ctx.get_assignment_for_role("semantic_review")
    assert provider == "provider-reviewer"
    assert model == "model-reviewer"


def test_policy_enforces_reviewer_not_equal_command_actor_for_blocking_issue():
    """policies.py: IssueResolution.reviewer != command.actor must be enforced for blocking issues."""
    state = sample_state()
    plan_v1 = sample_plan(state)  # revision 1
    issue = Issue(
        id="ISSUE-BLK-1",
        run_id=state.run.id,
        severity=IssueSeverity.BLOCKING,
        status=IssueStatus.PROPOSED_RESOLUTION,
        based_on_revision=1,
        claim="Potential race condition",
        impact="Data corruption",
        suggested_resolution="Add mutex",
        verification_request="Verify lock",
        requirement_ids=["REQ-001"],
    )

    # Create plan revision 2 addressing this issue
    step = PlanStep(
        id="STEP-1",
        objective="Add mutex",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["lock.py"],
        completion_criteria=["tests pass"],
    )
    plan_v2 = PlanRevision(
        id="PLAN-2",
        run_id=state.run.id,
        revision=2,
        based_on_revision=1,
        requirements_revision=state.task.revision,
        snapshot_id=None,
        steps=[step],
        issues_addressed=["ISSUE-BLK-1"],
    )

    state = state.model_copy(update={"plans": [plan_v1, plan_v2], "issues": [issue]})

    # 1. When reviewer == command.actor -> raises InvalidState
    resolution_same_actor = IssueResolution(
        text="Mutex added",
        reviewed_revision=2,
        reviewer="reviewer-agent",
        review_result="PASS",
        review_note="Approved",
    )
    cmd_same = ChangeIssue(
        expected_revision=state.run.revision,
        node="review",
        logical_operation_id="resolve-1",
        actor="reviewer-agent",  # Same as reviewer!
        issue_id="ISSUE-BLK-1",
        status=IssueStatus.RESOLVED,
        reason="Approved",
        resolution=resolution_same_actor,
    )

    with pytest.raises(InvalidState, match="independent review"):
        apply_mutation(state, cmd_same, utc_now())

    # 2. When reviewer != command.actor -> succeeds
    cmd_distinct = ChangeIssue(
        expected_revision=state.run.revision,
        node="review",
        logical_operation_id="resolve-2",
        actor="orchestration-controller",  # Different from reviewer!
        issue_id="ISSUE-BLK-1",
        status=IssueStatus.RESOLVED,
        reason="Approved",
        resolution=resolution_same_actor,
    )
    updated, _ = apply_mutation(state, cmd_distinct, utc_now())
    resolved_issue = next(i for i in updated.issues if i.id == "ISSUE-BLK-1")
    assert resolved_issue.status == IssueStatus.RESOLVED


def test_workflow_controller_resolve_issue_satisfies_actor_separation():
    """WorkflowController.resolve_issue satisfies reviewer != command.actor in the workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            plan_v1 = sample_plan(state)
            store.create(state.task, state.run, state.snapshot)

            lease = store.acquire(state.run.id, owner="test-owner", ttl=30)
            ctrl = WorkflowController(store, lease, actor="orchestration-controller")

            # Record issue
            issue = Issue(
                id="ISSUE-BLK-2",
                run_id=state.run.id,
                severity=IssueSeverity.BLOCKING,
                status=IssueStatus.OPEN,
                based_on_revision=0,
                claim="Missing input validation",
                impact="Injection vulnerability",
                verification_request="Verify validation logic",
                suggested_resolution="Validate all inputs",
                requirement_ids=["REQ-001"],
            )
            ctrl.record_issue(issue)

            # Commit plan revision 1 addressing this issue
            step = PlanStep(
                id="STEP-1",
                objective="Input validation",
                requirement_ids=["REQ-001"],
                validation="pytest",
                deliverables=["val.py"],
                completion_criteria=["tests pass"],
            )
            plan_v1 = PlanRevision(
                id="PLAN-1",
                run_id=state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=state.task.revision,
                snapshot_id=None,
                steps=[step],
                issues_addressed=["ISSUE-BLK-2"],
            )
            ctrl.commit_plan_revision(plan_v1)

            # Resolve issue through controller with reviewer="reviewer"
            res_state = ctrl.resolve_issue(
                issue_id="ISSUE-BLK-2",
                reviewer="reviewer",
                review_result="PASS",
                review_note="Verified in plan 1",
                resolution_text="Input validation implemented",
            )
            resolved = next(i for i in res_state.issues if i.id == "ISSUE-BLK-2")
            assert resolved.status == IssueStatus.RESOLVED
            assert resolved.resolution.reviewer == "reviewer"
