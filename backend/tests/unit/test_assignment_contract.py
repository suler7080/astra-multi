"""Deterministic tests for the structured assignment/ownership contract."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astra_multi.domain.assignment import (
    ASSIGNMENT_COMMIT_RULES,
    infer_expected_worker_count,
    task_requires_assignment,
    validate_assignment_contract,
)
from astra_multi.domain.commands import CommitPlan
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    ArtifactType,
    AssignmentMatrix,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementType,
    SharedFilePolicy,
    TaskSpec,
    WorkerAssignment,
)
from astra_multi.domain.policies import InvalidState, apply_mutation


def _task(*, org: bool = True, text: str = "Phân công cho đúng 4 lập trình viên") -> TaskSpec:
    return TaskSpec(
        id="TASK-1",
        goal="Build the application",
        requirements=[
            Requirement(
                id="REQ-1",
                text=text,
                acceptance="Every worker owns a disjoint file set",
                req_type=RequirementType.ORG if org else RequirementType.TECH,
                expected_artifact_type=(
                    ArtifactType.ASSIGNMENT_TABLE if org else ArtifactType.NARRATIVE
                ),
            )
        ],
    )


def _worker(
    role: str,
    files: list[str],
    *,
    requirement_ids: list[str] | None = None,
    step_ids: list[str] | None = None,
) -> WorkerAssignment:
    return WorkerAssignment(
        worker_role=role,
        display_name=role,
        responsibilities=[f"Own {', '.join(files) or 'nothing'}"],
        owned_files=files,
        requirement_ids=(
            requirement_ids if requirement_ids is not None else ["REQ-1"]
        ),
        step_ids=step_ids if step_ids is not None else [],
    )


def _step(
    step_id: str,
    role: str,
    files: list[str],
    *,
    targets: list[str] | None = None,
    requirement_ids: list[str] | None = None,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        objective=f"Work on {', '.join(files) or 'nothing'}",
        requirement_ids=(
            requirement_ids if requirement_ids is not None else ["REQ-1"]
        ),
        dependencies=[],
        validation="pytest",
        deliverables=["module"],
        completion_criteria=["tests pass"],
        worker_role=role,
        owned_files=files,
        targets=targets or [],
    )


def _plan(
    *,
    matrix: AssignmentMatrix | None,
    steps: list[PlanStep],
) -> PlanRevision:
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=steps,
    )
    if matrix is not None:
        # model_copy skips re-validation so tests can exercise malformed
        # matrices that the normal contract would reject at construction.
        plan = plan.model_copy(update={"assignment_matrix": matrix})
    return plan


def _rules(violations) -> set[str]:
    return {violation.rule_id for violation in violations}


def test_task_requires_assignment_and_infers_worker_count():
    assert task_requires_assignment(_task()) is True
    assert infer_expected_worker_count(_task()) == 4
    assert task_requires_assignment(_task(org=False)) is False


def test_missing_matrix_is_rule_001_and_blocks_commit():
    task = _task()
    plan = _plan(matrix=None, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    assert "RULE-ASSIGN-001" in _rules(validate_assignment_contract(task, plan))
    assert "RULE-ASSIGN-001" in ASSIGNMENT_COMMIT_RULES

    state = sample_state()
    state = state.model_copy(update={"tasks": [task]})
    with pytest.raises(InvalidState, match="RULE-ASSIGN-001"):
        apply_mutation(
            state,
            CommitPlan(
                expected_revision=1,
                node="plan",
                logical_operation_id="op-1",
                actor="planner",
                plan=plan,
            ),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_duplicate_worker_roles_are_rule_002():
    task = _task()
    matrix = AssignmentMatrix.model_construct(
        workers=[
            _worker("w1", ["src/a.py"]),
            _worker("w1", ["src/b.py"]),
        ],
        shared_files=[],
        expected_worker_count=2,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    assert "RULE-ASSIGN-002" in _rules(validate_assignment_contract(task, plan))


def test_worker_count_mismatch_is_rule_003():
    task = _task(text="Phân công cho đúng 4 lập trình viên")
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"])],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-003" in _rules(violations)
    assert "RULE-ASSIGN-003" not in ASSIGNMENT_COMMIT_RULES


def test_empty_worker_is_rule_004():
    task = _task()
    empty = WorkerAssignment.model_construct(
        worker_role="w1",
        display_name="w1",
        responsibilities=[],
        owned_files=[],
        requirement_ids=[],
        step_ids=[],
    )
    matrix = AssignmentMatrix.model_construct(
        workers=[empty], shared_files=[], expected_worker_count=1
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    assert "RULE-ASSIGN-004" in _rules(validate_assignment_contract(task, plan))


def test_invalid_owned_path_is_rule_005():
    task = _task()
    invalid = WorkerAssignment.model_construct(
        worker_role="w1",
        display_name="w1",
        responsibilities=["Own a file"],
        owned_files=["../escape.py"],
        requirement_ids=["REQ-1"],
        step_ids=["STEP-1"],
    )
    matrix = AssignmentMatrix.model_construct(
        workers=[invalid], shared_files=[], expected_worker_count=1
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    assert "RULE-ASSIGN-005" in _rules(validate_assignment_contract(task, plan))


def test_cross_role_overlap_is_rule_006():
    task = _task(text="Phân công cho 2 lập trình viên")
    matrix = AssignmentMatrix(
        workers=[
            _worker("w1", ["src/shared.py"], step_ids=["STEP-1"]),
            _worker("w2", ["src/shared.py"], step_ids=["STEP-2"]),
        ],
        expected_worker_count=2,
    )
    plan = _plan(
        matrix=matrix,
        steps=[
            _step("STEP-1", "w1", ["src/shared.py"]),
            _step("STEP-2", "w2", ["src/shared.py"]),
        ],
    )

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-006" in _rules(violations)
    assert "RULE-ASSIGN-006" not in ASSIGNMENT_COMMIT_RULES


def test_unowned_requirement_is_rule_007():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], requirement_ids=[], step_ids=["STEP-1"])],
        expected_worker_count=1,
    )
    plan = _plan(
        matrix=matrix,
        steps=[_step("STEP-1", "w1", ["src/a.py"], requirement_ids=["REQ-OTHER"])],
    )

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-007" in _rules(violations)
    assert any(v.requirement_id == "REQ-1" for v in violations)


def test_step_without_owner_or_files_is_rule_008():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-1"])],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "unassigned", [])])

    assert "RULE-ASSIGN-008" in _rules(validate_assignment_contract(task, plan))


def test_target_file_not_owned_is_rule_009():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-1"])],
        expected_worker_count=1,
    )
    plan = _plan(
        matrix=matrix,
        steps=[_step("STEP-1", "w1", ["src/a.py"], targets=["src/extra.py"])],
    )

    assert "RULE-ASSIGN-009" in _rules(validate_assignment_contract(task, plan))


def test_matrix_step_file_mismatch_is_rule_010():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-1"])],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/b.py"])])

    assert "RULE-ASSIGN-010" in _rules(validate_assignment_contract(task, plan))


def test_shared_file_policy_conflict_is_rule_011():
    task = _task(text="Phân công cho 2 lập trình viên")
    matrix = AssignmentMatrix(
        workers=[
            _worker("w1", ["src/shared.py"], step_ids=["STEP-1"]),
            _worker("w2", ["src/shared.py"], step_ids=["STEP-2"]),
        ],
        shared_files=[
            SharedFilePolicy(path="src/shared.py", owner_worker="w1"),
        ],
        expected_worker_count=2,
    )
    plan = _plan(
        matrix=matrix,
        steps=[
            _step("STEP-1", "w1", ["src/shared.py"]),
            _step("STEP-2", "w2", ["src/shared.py"]),
        ],
    )

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-011" in _rules(violations)
    assert "RULE-ASSIGN-011" not in ASSIGNMENT_COMMIT_RULES


def test_invalid_shared_path_is_rule_005_not_a_crash():
    task = _task()
    matrix = AssignmentMatrix.model_construct(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-1"])],
        shared_files=[
            SharedFilePolicy.model_construct(
                path="../shared.py",
                owner_worker="w1",
                access="owner_only",
                reason=None,
            )
        ],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-005" in _rules(violations)


def test_stale_worker_step_ids_is_rule_012():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-999"])],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "w1", ["src/a.py"])])

    assert "RULE-ASSIGN-012" in _rules(validate_assignment_contract(task, plan))


def test_worker_cannot_claim_another_workers_step_is_rule_012():
    task = _task(text="Phân công cho 2 lập trình viên")
    matrix = AssignmentMatrix(
        workers=[
            _worker("w1", ["src/a.py"], step_ids=["STEP-1", "STEP-2"]),
            _worker("w2", ["src/b.py"], step_ids=["STEP-2"]),
        ],
        expected_worker_count=2,
    )
    plan = _plan(
        matrix=matrix,
        steps=[
            _step("STEP-1", "w1", ["src/a.py"]),
            _step("STEP-2", "w2", ["src/b.py"]),
        ],
    )

    violations = validate_assignment_contract(task, plan)

    assert "RULE-ASSIGN-012" in _rules(violations)
    assert any("owned by 'w2'" in violation.message for violation in violations)


def test_non_org_task_keeps_backward_compatibility():
    state = sample_state()
    plan = sample_plan(state)

    updated, result = apply_mutation(
        state,
        CommitPlan(
            expected_revision=1,
            node="plan",
            logical_operation_id="op-1",
            actor="planner",
            plan=plan,
        ),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert updated.plan is not None
    assert result["plan_revision"] == 1


def test_unowned_step_blocks_commit_for_org_task():
    task = _task()
    matrix = AssignmentMatrix(
        workers=[_worker("w1", ["src/a.py"], step_ids=["STEP-1"])],
        expected_worker_count=1,
    )
    plan = _plan(matrix=matrix, steps=[_step("STEP-1", "unassigned", [])])
    state = sample_state().model_copy(update={"tasks": [task]})

    with pytest.raises(InvalidState, match="RULE-ASSIGN-008"):
        apply_mutation(
            state,
            CommitPlan(
                expected_revision=1,
                node="plan",
                logical_operation_id="op-1",
                actor="planner",
                plan=plan,
            ),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
