"""Deterministic assignment/ownership contract validation.

The assignment matrix is structured data.  These checks never inspect prose or
keyword tables; they compare canonical ownership keys against the committed
``PlanStep`` records and the current task requirements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import AssignmentMatrix, PlanRevision, RequirementType, TaskSpec
from .paths import PathValidationError, path_key

_COUNT_PATTERN = re.compile(
    r"(?:đúng\s+|exactly\s+)?(\d{1,2})\s*"
    r"(?:lập\s+trình\s+viên|thành\s+viên|người|kỹ\s+sư|"
    r"dev(?:eloper)?s?|members?|workers?|roles?|people)",
    re.IGNORECASE,
)

# Rules that make a plan ineligible to commit at all: the ownership contract is
# incomplete or contradicts the plan graph.
ASSIGNMENT_COMMIT_RULES: frozenset[str] = frozenset(
    {
        "RULE-ASSIGN-001",  # missing matrix
        "RULE-ASSIGN-002",  # duplicate worker roles
        "RULE-ASSIGN-004",  # empty worker
        "RULE-ASSIGN-005",  # invalid owned path
        "RULE-ASSIGN-007",  # requirement unowned
        "RULE-ASSIGN-008",  # step without owner/files
        "RULE-ASSIGN-009",  # target file not owned
        "RULE-ASSIGN-010",  # matrix/step file mismatch
        "RULE-ASSIGN-012",  # stale worker step_ids
    }
)

# Rules that describe a risky but well-formed ownership layout.  These block
# FINAL and force an explicit human decision instead of a silent commit failure.
ASSIGNMENT_HUMAN_REVIEW_RULES: frozenset[str] = frozenset(
    {
        "RULE-ASSIGN-006",  # cross-role overlap
        "RULE-ASSIGN-011",  # shared-file policy conflict
    }
)


@dataclass(frozen=True)
class AssignmentViolation:
    rule_id: str
    entity_ref: str
    message: str
    remediation: str
    requirement_id: str | None = None


def task_requires_assignment(task: TaskSpec) -> bool:
    """True when the task explicitly asks for organisational ownership."""
    from .models import ArtifactType

    return any(
        requirement.req_type == RequirementType.ORG
        or requirement.expected_artifact_type == ArtifactType.ASSIGNMENT_TABLE
        for requirement in task.requirements
    )


def infer_expected_worker_count(task: TaskSpec) -> int | None:
    """Infer an exact worker count from the task wording, if unambiguous."""
    counts: set[int] = set()
    for requirement in task.requirements:
        for match in _COUNT_PATTERN.finditer(requirement.text):
            value = int(match.group(1))
            if 1 <= value <= 50:
                counts.add(value)
    if len(counts) == 1:
        return counts.pop()
    return None


def _matrix_paths(matrix: AssignmentMatrix | None) -> dict[str, set[str]]:
    if matrix is None:
        return {}
    return {
        worker.worker_role: {path_key(path) for path in worker.owned_files}
        for worker in matrix.workers
    }


def validate_assignment_contract(
    task: TaskSpec, plan: PlanRevision
) -> list[AssignmentViolation]:
    """Return every deterministic ownership violation for the candidate plan."""
    violations: list[AssignmentViolation] = []
    seen: set[tuple[str, str, str]] = set()

    def add(
        rule_id: str,
        entity_ref: str,
        message: str,
        remediation: str,
        requirement_id: str | None = None,
    ) -> None:
        key = (rule_id, entity_ref, message)
        if key in seen:
            return
        seen.add(key)
        violations.append(
            AssignmentViolation(
                rule_id=rule_id,
                entity_ref=entity_ref,
                message=message,
                remediation=remediation,
                requirement_id=requirement_id,
            )
        )

    matrix = plan.assignment_matrix
    if matrix is None:
        add(
            "RULE-ASSIGN-001",
            f"plan:{plan.id}",
            "Task requires an assignment matrix but the plan does not contain one.",
            "Emit assignment_matrix with workers, responsibilities, owned_files, requirement_ids and shared_files.",
        )

    workers = list(matrix.workers) if matrix is not None else []
    role_map = {worker.worker_role: worker for worker in workers}
    if len(role_map) != len(workers):
        add(
            "RULE-ASSIGN-002",
            f"plan:{plan.id}",
            "Assignment matrix contains duplicate worker roles.",
            "Use one unique worker_role per worker.",
        )

    inferred = infer_expected_worker_count(task)
    declared = matrix.expected_worker_count if matrix is not None else None
    expected = declared or inferred
    if declared is not None and inferred is not None and declared != inferred:
        add(
            "RULE-ASSIGN-003",
            f"plan:{plan.id}",
            f"Matrix declares {declared} workers but the task requires {inferred}.",
            "Set expected_worker_count to the exact number required by the task.",
        )
    elif expected is not None and len(workers) != expected:
        add(
            "RULE-ASSIGN-003",
            f"plan:{plan.id}",
            f"Assignment matrix has {len(workers)} workers; task requires exactly {expected}.",
            "Provide exactly one assignment per required worker.",
        )

    worker_files: dict[str, set[str]] = {}
    for worker in workers:
        if not worker.responsibilities or not worker.owned_files:
            add(
                "RULE-ASSIGN-004",
                f"worker:{worker.worker_role}",
                "Worker has no responsibilities or owned files.",
                "Give every worker at least one responsibility and one owned file.",
            )
        normalized: set[str] = set()
        for raw_path in worker.owned_files:
            try:
                normalized.add(path_key(raw_path))
            except PathValidationError as exc:
                add(
                    "RULE-ASSIGN-005",
                    f"worker:{worker.worker_role}",
                    f"Invalid owned path {raw_path!r}: {exc}",
                    "Owned files must be repository-relative paths without traversal or absolute prefixes.",
                )
        worker_files[worker.worker_role] = normalized

    owners_by_key: dict[str, list[str]] = {}
    for role, keys in worker_files.items():
        for key in keys:
            owners_by_key.setdefault(key, []).append(role)
    for key, owners in sorted(owners_by_key.items()):
        if len(owners) > 1:
            add(
                "RULE-ASSIGN-006",
                f"path:{key}",
                f"Owned file is claimed by multiple workers: {', '.join(sorted(owners))}.",
                "Give each file exactly one owner; coordinate shared changes through that owner.",
            )

    covered_requirements: set[str] = set()
    for worker in workers:
        covered_requirements.update(worker.requirement_ids)
    for step in plan.steps:
        if step.worker_role in role_map:
            covered_requirements.update(step.requirement_ids)
    for requirement in task.requirements:
        if requirement.id not in covered_requirements:
            add(
                "RULE-ASSIGN-007",
                f"requirement:{requirement.id}",
                f"Requirement {requirement.id} is not owned by any worker or assigned step.",
                "Map every requirement to at least one worker/step.",
                requirement_id=requirement.id,
            )

    step_by_id = {step.id: step for step in plan.steps}
    union_step_files: dict[str, set[str]] = {role: set() for role in role_map}
    for step in plan.steps:
        role = step.worker_role
        if not role or role == "unassigned":
            add(
                "RULE-ASSIGN-008",
                f"step:{step.id}",
                "Step has no worker_role.",
                "Assign the step to a worker declared in the assignment matrix.",
            )
        elif role not in role_map:
            add(
                "RULE-ASSIGN-008",
                f"step:{step.id}",
                f"Step worker_role {role!r} is not present in the assignment matrix.",
                "Add the worker to the matrix or use an existing worker_role.",
            )
        if not step.owned_files:
            add(
                "RULE-ASSIGN-008",
                f"step:{step.id}",
                "Step has no owned_files.",
                "List the exact repository files the worker may change for this step.",
            )
            continue

        step_keys: set[str] = set()
        for raw_path in step.owned_files:
            try:
                step_keys.add(path_key(raw_path))
            except PathValidationError as exc:
                add(
                    "RULE-ASSIGN-005",
                    f"step:{step.id}",
                    f"Invalid owned path {raw_path!r}: {exc}",
                    "Owned files must be repository-relative paths without traversal or absolute prefixes.",
                )
        if role in union_step_files:
            union_step_files[role].update(step_keys)

        matrix_keys = worker_files.get(role, set())
        extra = step_keys - matrix_keys
        if extra:
            add(
                "RULE-ASSIGN-010",
                f"step:{step.id}",
                f"Step owns files not declared for worker {role!r}: {sorted(extra)}.",
                "Make the worker's matrix owned_files match the files used by its steps.",
            )

        for raw_target in step.targets:
            try:
                target_key = path_key(raw_target)
            except PathValidationError as exc:
                add(
                    "RULE-ASSIGN-005",
                    f"step:{step.id}",
                    f"Invalid target path {raw_target!r}: {exc}",
                    "Targets must be repository-relative paths without traversal or absolute prefixes.",
                )
                continue
            if target_key not in step_keys:
                add(
                    "RULE-ASSIGN-009",
                    f"step:{step.id}",
                    f"Target file {raw_target!r} is not owned by this step.",
                    "Add every target file to the step's owned_files.",
                )

        if role in role_map:
            assigned = role_map[role]
            if assigned.step_ids and step.id not in assigned.step_ids:
                add(
                    "RULE-ASSIGN-012",
                    f"worker:{role}",
                    f"Step {step.id} is not listed in worker {role!r} step_ids.",
                    "Keep worker step_ids in sync with PlanStep.worker_role.",
                )

    for role, assigned in role_map.items():
        for assigned_step_id in assigned.step_ids:
            assigned_step = step_by_id.get(assigned_step_id)
            if assigned_step is None:
                add(
                    "RULE-ASSIGN-012",
                    f"worker:{role}",
                    f"Worker {role!r} references unknown step {assigned_step_id!r}.",
                    "Remove stale step IDs from the assignment matrix.",
                )
            elif assigned_step.worker_role != role:
                add(
                    "RULE-ASSIGN-012",
                    f"worker:{role}",
                    f"Worker {role!r} lists step {assigned_step_id!r}, which is "
                    f"owned by {assigned_step.worker_role!r}.",
                    "Keep worker step_ids in sync with PlanStep.worker_role.",
                )

    shared_keys: set[str] = set()
    for shared in matrix.shared_files if matrix is not None else []:
        try:
            key = path_key(shared.path)
        except PathValidationError as exc:
            add(
                "RULE-ASSIGN-005",
                f"shared:{shared.path}",
                f"Invalid shared path {shared.path!r}: {exc}",
                "Shared files must be repository-relative paths without traversal or absolute prefixes.",
            )
            continue
        if key in shared_keys:
            add(
                "RULE-ASSIGN-011",
                f"path:{key}",
                "Shared file is declared more than once.",
                "Declare each shared file policy exactly once.",
            )
        shared_keys.add(key)
        owners = owners_by_key.get(key, [])
        if len(owners) != 1:
            add(
                "RULE-ASSIGN-011",
                f"path:{key}",
                f"Shared file must have exactly one owner; found {len(owners)}.",
                "Assign the shared file to exactly one worker and coordinate access through that owner.",
            )
        elif owners[0] != shared.owner_worker:
            add(
                "RULE-ASSIGN-011",
                f"path:{key}",
                f"Shared file owner {shared.owner_worker!r} does not match the actual owner {owners[0]!r}.",
                "Make shared_files.owner_worker match the single worker that owns the file.",
            )

    for role, keys in worker_files.items():
        unassigned_to_steps = keys - union_step_files.get(role, set()) - shared_keys
        if unassigned_to_steps and any(
            step.worker_role == role for step in plan.steps
        ):
            add(
                "RULE-ASSIGN-010",
                f"worker:{role}",
                f"Worker {role!r} owns files that no step uses and that are not shared: "
                f"{sorted(unassigned_to_steps)}.",
                "Assign those files to a step or declare them as shared files.",
            )

    return violations
