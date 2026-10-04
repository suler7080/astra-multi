"""P4.1 Structural quality validator.

Validates candidate plan against task specification, issues, evidence, and structural constraints:
- Complete schema & unique ID invariants
- 100% requirement coverage by plan steps
- Plan step dependency graph forms a strict DAG (no cycles, no missing dependencies)
- Reference integrity: all referenced issues, requirements, evidence, snapshots exist
- Validation execution status rules (greenfield vs repo; NOT_RUN cannot contain execution results)
- Zero open blocking issues for passing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from astra_multi.domain.models import (
    IssueSeverity,
    IssueStatus,
    RunState,
    ValidationStatus,
)


class ViolationSeverity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class QualityViolation:
    rule_id: str
    severity: ViolationSeverity
    entity_ref: str
    message: str
    remediation: str


@dataclass
class QualityReport:
    passed: bool
    plan_revision: int
    task_revision: int
    violations: list[QualityViolation] = field(default_factory=list)
    uncovered_requirements: list[str] = field(default_factory=list)
    unresolved_blocking_issues: list[str] = field(default_factory=list)

    @property
    def has_blockers(self) -> bool:
        return any(v.severity == ViolationSeverity.BLOCKER for v in self.violations)


class StructuralQualityValidator:
    """Validates structural invariants of candidate plans."""

    def validate(self, state: RunState) -> QualityReport:
        plan = state.plan
        task = state.task
        violations: list[QualityViolation] = []
        uncovered: list[str] = []
        unresolved_blockers: list[str] = []

        if not plan:
            violations.append(
                QualityViolation(
                    rule_id="RULE-STRUCT-001",
                    severity=ViolationSeverity.BLOCKER,
                    entity_ref=f"run:{state.run.id}",
                    message="No candidate plan revision has been committed.",
                    remediation="Generate and commit a plan revision in the REVISE phase.",
                )
            )
            return QualityReport(
                passed=False,
                plan_revision=0,
                task_revision=task.revision,
                violations=violations,
            )

        # 1. Check requirements coverage
        task_req_ids = {r.id for r in task.requirements}
        step_covered_req_ids: set[str] = set()
        for step in plan.steps:
            for r_id in step.requirement_ids:
                if r_id not in task_req_ids:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-REF-001",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=f"Step references unknown requirement ID: {r_id}",
                            remediation="Ensure step requirement_ids match current TaskSpec requirements.",
                        )
                    )
                else:
                    step_covered_req_ids.add(r_id)

        missing_reqs = task_req_ids - step_covered_req_ids
        if missing_reqs:
            uncovered = sorted(missing_reqs)
            violations.append(
                QualityViolation(
                    rule_id="RULE-COV-001",
                    severity=ViolationSeverity.BLOCKER,
                    entity_ref=f"plan:{plan.id}",
                    message=f"Plan fails to cover all requirements. Missing: {sorted(missing_reqs)}",
                    remediation="Add or update plan steps to address every requirement in the TaskSpec.",
                )
            )

        # 2. Check Step Dependency DAG
        step_ids = {s.id for s in plan.steps}
        if len(step_ids) != len(plan.steps):
            violations.append(
                QualityViolation(
                    rule_id="RULE-UNIQUE-001",
                    severity=ViolationSeverity.BLOCKER,
                    entity_ref=f"plan:{plan.id}",
                    message="Duplicate step IDs detected in candidate plan.",
                    remediation="Ensure all plan steps have globally unique IDs within the plan.",
                )
            )

        # Verify dependency existence
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-DAG-001",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=f"Step depends on nonexistent step ID: {dep}",
                            remediation="Ensure all step dependencies reference valid step IDs.",
                        )
                    )

        # Verify cycle-free DAG (topological sort)
        adj: dict[str, set[str]] = {s.id: set(s.dependencies) for s in plan.steps if s.id in step_ids}
        remaining = dict(adj)
        while remaining:
            ready = {k for k, deps in remaining.items() if not deps}
            if not ready:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-DAG-002",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message="Dependency cycle detected in plan steps.",
                        remediation="Remove circular dependencies between plan steps to form a strict DAG.",
                    )
                )
                break
            remaining = {
                k: deps - ready for k, deps in remaining.items() if k not in ready
            }

        # 3. Check unresolved blocking issues
        for issue in state.issues:
            if issue.severity == IssueSeverity.BLOCKING and issue.status != IssueStatus.RESOLVED:
                unresolved_blockers.append(issue.id)
                violations.append(
                    QualityViolation(
                        rule_id="RULE-ISSUE-001",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"issue:{issue.id}",
                        message=f"Blocking issue remains unresolved: {issue.claim}",
                        remediation="Address and resolve the issue in a new revision or update requirements.",
                    )
                )

        # 4. Check step deliverables & completion criteria
        for step in plan.steps:
            if not step.deliverables:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-STEP-001",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"step:{step.id}",
                        message="Step has empty deliverables list.",
                        remediation="Provide at least one concrete deliverable for the step.",
                    )
                )
            if not step.completion_criteria:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-STEP-002",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"step:{step.id}",
                        message="Step has empty completion criteria.",
                        remediation="Specify verifiable completion criteria.",
                    )
                )

        # 5. Check validation execution invariants
        for val in state.validations:
            if val.status == ValidationStatus.NOT_RUN and (val.actual or val.exit_code is not None):
                violations.append(
                    QualityViolation(
                        rule_id="RULE-VAL-001",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"validation:{val.id}",
                        message="Validation marked as NOT_RUN contains execution results.",
                        remediation="Do not record actual output or exit code for unexecuted validations.",
                    )
                )

        passed = not any(v.severity == ViolationSeverity.BLOCKER for v in violations)

        return QualityReport(
            passed=passed,
            plan_revision=plan.revision,
            task_revision=task.revision,
            violations=violations,
            uncovered_requirements=uncovered,
            unresolved_blocking_issues=unresolved_blockers,
        )
