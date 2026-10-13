"""Test suite for Phase 2 [G]: Reviewer chấm theo từng requirement + hỗ trợ DUPLICATE."""

import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError

from astra_multi.agents.roles import (
    IssueReport,
    IssueResolutionReport,
    RequirementVerdict,
    ReviewOutput,
    format_review_prompt,
    format_semantic_review_prompt,
    ContextBundle,
)
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Requirement,
    Run,
    RunPhase,
    RunState,
    RunStatus,
    TaskSpec,
)
from astra_multi.exports.finalization import FinalizationEvaluator, SemanticReviewAssessment
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph
from astra_multi.persistence.sqlite import SQLiteStore


def test_requirement_verdict_schema_and_review_output_validation():
    verdict_pass = RequirementVerdict(
        requirement_id="REQ-001",
        restated="Agent leader election",
        mechanism="Raft consensus",
        verdict="PASS",
    )
    assert verdict_pass.verdict == "PASS"

    verdict_fail = RequirementVerdict(
        requirement_id="REQ-002",
        restated="Crash recovery",
        mechanism="Optimistic locking",
        verdict="FAIL",
        gap="Optimistic locking does not solve crash recovery",
    )
    assert verdict_fail.verdict == "FAIL"

    # ReviewOutput includes requirement_verdicts
    review = ReviewOutput(
        summary="Evaluated 2 requirements",
        requirement_verdicts=[verdict_pass, verdict_fail],
    )
    assert len(review.requirement_verdicts) == 2

    # Validation error when expected requirement is missing
    with pytest.raises(ValidationError, match="missing requirement verdicts"):
        ReviewOutput.model_validate(
            {
                "summary": "Only 1 requirement evaluated",
                "requirement_verdicts": [verdict_pass.model_dump()],
            },
            context={"expected_requirements": ["REQ-001", "REQ-002"]},
        )


def test_issue_resolution_duplicate_support():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-owner", ttl=30)
            ctrl = WorkflowController(store, lease, actor="orchestration-controller")

            # Create original issue
            issue1 = Issue(
                id="ISSUE-ORIG-1",
                run_id=state.run.id,
                severity=IssueSeverity.WARNING,
                status=IssueStatus.OPEN,
                based_on_revision=0,
                claim="Missing timeout handling",
                impact="Hung worker process",
                verification_request="Verify timeout",
                suggested_resolution="Add timeout to worker",
                requirement_ids=["REQ-001"],
            )
            ctrl.record_issue(issue1)

            # Create duplicate issue
            issue2 = Issue(
                id="ISSUE-DUP-2",
                run_id=state.run.id,
                severity=IssueSeverity.WARNING,
                status=IssueStatus.OPEN,
                based_on_revision=0,
                claim="Worker hang on network partition",
                impact="Hung worker process",
                verification_request="Verify partition recovery",
                suggested_resolution="Set connection timeout",
                requirement_ids=["REQ-001"],
            )
            ctrl.record_issue(issue2)

            # Resolve issue2 as DUPLICATE of issue1
            updated_state = ctrl.resolve_issue(
                issue_id="ISSUE-DUP-2",
                reviewer="reviewer",
                review_result="DUPLICATE",
                duplicate_of="ISSUE-ORIG-1",
                review_note="Duplicate of ISSUE-ORIG-1",
            )

            resolved_dup = next(i for i in updated_state.issues if i.id == "ISSUE-DUP-2")
            assert resolved_dup.status == IssueStatus.DUPLICATE
            assert resolved_dup.duplicate_of == "ISSUE-ORIG-1"


def test_semantic_review_with_fail_verdict_results_in_partial():
    """Plan dùng cơ chế sai vấn đề với fake LLM trả verdict FAIL -> semantic review passed == False -> PARTIAL."""
    task = TaskSpec(
        id="TASK-1",
        goal="Engine Crash Recovery",
        requirements=[
            Requirement(
                id="REQ-001",
                text="Khôi phục khi agent lỗi",
                acceptance="Plan nêu cơ chế cụ thể đáp ứng yêu cầu này: Khôi phục khi agent lỗi",
            )
        ],
    )
    run = Run(
        id="RUN-FAIL-VERDICT",
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="greenfield",
        config_hash="0" * 64,
    )
    # Plan uses wrong mechanism: optimistic locking for crash recovery
    step = PlanStep(
        id="STEP-1",
        objective="Use optimistic locking on db records",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["lock.py"],
        completion_criteria=["tests pass"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id=run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )
    state = RunState(run=run, tasks=[task], plans=[plan], snapshot=None)

    # Reviewer returns verdict FAIL
    review_output = ReviewOutput(
        summary="Cơ chế optimistic locking không giải quyết yêu cầu khôi phục khi agent lỗi",
        requirement_verdicts=[
            RequirementVerdict(
                requirement_id="REQ-001",
                restated="Khôi phục khi agent lỗi",
                mechanism="Optimistic locking",
                verdict="FAIL",
                gap="Optimistic locking phát hiện xung đột ghi, không khôi phục trạng thái khi agent bị crash",
            )
        ],
    )

    # Calculate assessment
    failed_verdicts = [v for v in review_output.requirement_verdicts if v.verdict != "PASS"]
    assessment_passed = (len(failed_verdicts) == 0)
    assert assessment_passed is False

    assessment = SemanticReviewAssessment(
        passed=assessment_passed,
        reviewed_plan_revision=1,
        feedback=review_output.summary,
        concerns=[f"[{v.requirement_id}] Verdict {v.verdict}: {v.gap}" for v in failed_verdicts],
    )

    evaluator = FinalizationEvaluator()
    eval_result = evaluator.evaluate(state=state, semantic_review=assessment)
    assert eval_result.target_status == RunStatus.PARTIAL
    assert "Semantic review did not pass" in eval_result.reason


def test_prompts_instruct_mechanism_and_duplicate_check():
    bundle = ContextBundle(
        run_id="RUN-1",
        snapshot_id=None,
        role="reviewer",
        phase=RunPhase.REVIEW,
        content="Context",
        source_ids=(),
        truncated_ids=(),
        omitted_ids=(),
        token_count=100,
        tokenizer="cl100k_base",
        omitted_repo_paths=(),
    )
    from astra_multi.agents.roles import ProposalOutput
    prop = ProposalOutput(approach="Test approach")

    rev_msgs = format_review_prompt(bundle, prop)
    rev_system = rev_msgs[0]["content"]
    assert "cơ chế" in rev_system.lower() or "mechanism" in rev_system.lower()
    assert "duplicate" in rev_system.lower() or "trùng" in rev_system.lower()

    sem_msgs = format_semantic_review_prompt(bundle, {}, [])
    sem_system = sem_msgs[0]["content"]
    assert "cơ chế" in sem_system.lower() or "mechanism" in sem_system.lower()
    assert "duplicate" in sem_system.lower() or "trùng" in sem_system.lower()
