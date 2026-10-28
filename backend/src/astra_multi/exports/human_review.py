"""Risk-based human escalation for finalization.

The rules here do not grant or deny filesystem access.  They decide when an
otherwise complete run still needs an explicit human decision because the plan
or its execution crossed a risk boundary (ownership overlap, out-of-scope
changes, sensitive files, contradictory review evidence, and so on).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astra_multi.domain.assignment import (
    ASSIGNMENT_HUMAN_REVIEW_RULES,
    task_requires_assignment,
    validate_assignment_contract,
)
from astra_multi.domain.models import ExecutionStatus, RunState
from astra_multi.domain.paths import is_sensitive_path
from astra_multi.exports.quality_validator import QualityReport

if TYPE_CHECKING:
    from astra_multi.exports.finalization import SemanticReviewAssessment


@dataclass(frozen=True)
class HumanReviewTrigger:
    code: str
    message: str
    details: tuple[str, ...] = ()


@dataclass
class HumanReviewEvaluation:
    triggers: list[HumanReviewTrigger] = field(default_factory=list)
    approved: bool = False
    plan_revision: int = 0

    @property
    def required(self) -> bool:
        return bool(self.triggers) and not self.approved

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(trigger.code for trigger in self.triggers)


_MIGRATION_AUTH_SECURITY = re.compile(
    r"(^|/)(migrations?|alembic|auth|authentication|authorization|security|"
    r"schema|crypto|secrets?|credentials)(/|$)|(^|/)\.env",
    re.IGNORECASE,
)


def _record_paths(state: RunState) -> set[str]:
    paths: set[str] = set()
    for record in state.execution_records:
        paths.update(record.changed_files)
        paths.update(record.created_files)
        paths.update(record.deleted_files)
    return paths


def _plan_paths(state: RunState) -> set[str]:
    paths: set[str] = set()
    if state.plan is None:
        return paths
    for step in state.plan.steps:
        paths.update(step.owned_files)
        paths.update(step.targets)
    if state.plan.assignment_matrix is not None:
        for worker in state.plan.assignment_matrix.workers:
            paths.update(worker.owned_files)
        for shared in state.plan.assignment_matrix.shared_files:
            paths.add(shared.path)
    return paths


def _approved(state: RunState, plan_revision: int) -> bool:
    return any(
        approval.plan_revision == plan_revision
        for approval in state.human_review_approvals
    )


def _add(
    triggers: list[HumanReviewTrigger],
    code: str,
    message: str,
    details: list[str] | tuple[str, ...] = (),
) -> None:
    if any(trigger.code == code for trigger in triggers):
        return
    triggers.append(
        HumanReviewTrigger(
            code=code,
            message=message,
            details=tuple(str(item) for item in details),
        )
    )


def evaluate_human_review(
    state: RunState,
    quality_report: QualityReport,
    semantic_review: "SemanticReviewAssessment | None" = None,
) -> HumanReviewEvaluation:
    """Return every risk trigger for the current plan revision."""
    plan_revision = state.plan.revision if state.plan else 0
    triggers: list[HumanReviewTrigger] = []

    # 1. Ownership overlap / shared-file policy conflicts.
    overlap_details = [
        f"{violation.rule_id} {violation.entity_ref}: {violation.message}"
        for violation in quality_report.violations
        if violation.rule_id in ASSIGNMENT_HUMAN_REVIEW_RULES
    ]
    if not overlap_details and state.plan is not None and task_requires_assignment(
        state.task
    ):
        overlap_details = [
            f"{violation.rule_id} {violation.entity_ref}: {violation.message}"
            for violation in validate_assignment_contract(state.task, state.plan)
            if violation.rule_id in ASSIGNMENT_HUMAN_REVIEW_RULES
        ]
    if overlap_details:
        _add(
            triggers,
            "OWNERSHIP_OVERLAP",
            "Ownership contract contains cross-role overlap or a shared-file conflict.",
            overlap_details,
        )

    # 2. Post-run diff escaped the step's owned files.
    out_of_scope = [
        violation.message
        for violation in quality_report.violations
        if violation.rule_id in {"RULE-DIFF-001", "RULE-DIFF-002"}
    ]
    if out_of_scope:
        _add(
            triggers,
            "OUT_OF_SCOPE_CHANGE",
            "Worker execution changed files outside the declared owned_files.",
            out_of_scope,
        )

    # 3. Execution was denied or failed at runtime.
    runtime_details = [
        f"{record.step_id}: {record.status.value}: {'; '.join(record.violations)}"
        for record in state.execution_records
        if record.status != ExecutionStatus.PASSED
    ]
    if runtime_details:
        _add(
            triggers,
            "RUNTIME_SCOPE_VIOLATION",
            "At least one worker execution was denied or failed.",
            runtime_details,
        )

    # 4. Delete or rename operations.
    deleted = sorted(
        {
            path
            for record in state.execution_records
            for path in record.deleted_files
        }
    )
    if deleted:
        _add(
            triggers,
            "DELETE_OR_RENAME",
            "Execution deleted or renamed repository files.",
            deleted,
        )

    # 5. Sensitive, migration, auth or security paths.
    touched = _record_paths(state) | _plan_paths(state)
    sensitive = sorted(path for path in touched if is_sensitive_path(path))
    if sensitive:
        _add(
            triggers,
            "SENSITIVE_FILE",
            "Plan or execution touches sensitive files.",
            sensitive,
        )
    risky = sorted(
        path for path in touched if _MIGRATION_AUTH_SECURITY.search(path)
    )
    if risky:
        _add(
            triggers,
            "MIGRATION_AUTH_SECURITY",
            "Plan or execution changes migration, authentication or security code.",
            risky,
        )

    # 6. Validator/reviewer disagreement and missing evidence.
    conflicts = list(getattr(semantic_review, "validator_llm_conflicts", []) or [])
    if conflicts:
        _add(
            triggers,
            "VALIDATOR_LLM_CONFLICT",
            "Deterministic validators and the reviewer disagree.",
            conflicts,
        )
    missing_evidence = list(
        getattr(semantic_review, "missing_evidence", []) or []
    )
    if missing_evidence:
        _add(
            triggers,
            "MISSING_EVIDENCE",
            "At least one PASS/MET verdict lacks machine-checkable evidence.",
            missing_evidence,
        )

    # 7. Semantic PARTIAL verdicts.
    partials: list[str] = []
    for verdict in getattr(semantic_review, "requirement_verdicts", []) or []:
        status = (
            verdict.get("verdict")
            if isinstance(verdict, dict)
            else getattr(verdict, "verdict", None)
        )
        req_id = (
            verdict.get("requirement_id")
            if isinstance(verdict, dict)
            else getattr(verdict, "requirement_id", "")
        )
        if status == "PARTIAL":
            partials.append(str(req_id))
    if partials:
        _add(
            triggers,
            "SEMANTIC_PARTIAL",
            "Semantic review returned PARTIAL for at least one requirement.",
            partials,
        )

    # 8. Explicit plan uncertainty reported by the review pipeline.
    uncertainty = list(
        getattr(semantic_review, "plan_uncertainty", []) or []
    )
    if uncertainty:
        _add(
            triggers,
            "PLAN_UNCERTAINTY",
            "The review pipeline could not resolve plan uncertainty.",
            uncertainty,
        )

    return HumanReviewEvaluation(
        triggers=triggers,
        approved=_approved(state, plan_revision),
        plan_revision=plan_revision,
    )


def trigger_payload(evaluation: HumanReviewEvaluation) -> list[dict[str, Any]]:
    return [
        {
            "code": trigger.code,
            "message": trigger.message,
            "details": list(trigger.details),
        }
        for trigger in evaluation.triggers
    ]
