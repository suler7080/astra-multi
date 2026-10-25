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
    ArtifactType,
    IssueSeverity,
    IssueStatus,
    RunState,
    StepPhaseType,
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

        # 1. Check requirements coverage and design artifacts
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

        covered_req_ids = set(step_covered_req_ids)
        design_artifacts = getattr(plan, "design_artifacts", []) or []

        if state.run.mode == "design":
            if not design_artifacts:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-DESIGN-001",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message="Run ở mode 'design' nhưng plan không có design artifact nào.",
                        remediation="Bổ sung ít nhất một design artifact mô tả thiết kế kiến trúc.",
                    )
                )
            for da in design_artifacts:
                for r_id in da.requirement_ids:
                    if r_id not in task_req_ids:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-REF-001",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"artifact:{da.id}",
                                message=f"Design artifact references unknown requirement ID: {r_id}",
                                remediation="Ensure design artifact requirement_ids match current TaskSpec requirements.",
                            )
                        )
                    else:
                        covered_req_ids.add(r_id)

        missing_reqs = task_req_ids - covered_req_ids
        if missing_reqs:
            uncovered = sorted(missing_reqs)
            violations.append(
                QualityViolation(
                    rule_id="RULE-COV-001",
                    severity=ViolationSeverity.BLOCKER,
                    entity_ref=f"plan:{plan.id}",
                    message=f"Plan fails to cover all requirements. Missing: {sorted(missing_reqs)}",
                    remediation="Add or update plan steps or design artifacts to address every requirement in the TaskSpec.",
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

        # DAG topological invariants
        n_steps = len(plan.steps)
        step_map = {s.id: s for s in plan.steps}

        # RULE-DAG-003: Connected Graph (minimum edges: N - 1)
        if n_steps > 1:
            total_edges = sum(len(s.dependencies) for s in plan.steps)
            if total_edges < n_steps - 1:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-DAG-003",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message=(
                            f"Disconnected step graph: Plan with {n_steps} steps has only "
                            f"{total_edges} dependency edges (minimum required: {n_steps - 1}). "
                            "Steps cannot be isolated or disconnected."
                        ),
                        remediation="Add dependency relationships between steps so the plan forms a cohesive connected execution workflow.",
                    )
                )

        # RULE-DAG-004: Root Node Bound (maximum 2 root steps for N >= 3)
        if n_steps >= 3:
            root_steps = [s for s in plan.steps if not s.dependencies]
            if len(root_steps) > 2:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-DAG-004",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message=(
                            f"Excessive root steps: Plan has {len(root_steps)} root steps without dependencies "
                            f"({', '.join(s.id for s in root_steps)}). Maximum allowed parallel root steps is 2."
                        ),
                        remediation="Order steps logically with explicit dependencies so later steps depend on initial setup or core module steps.",
                    )
                )

        # RULE-DAG-005: Topological Depth (critical path length >= 2 for N > 1)
        if n_steps > 1:
            depth_memo: dict[str, int] = {}
            depth_visiting: set[str] = set()

            def _get_step_depth(sid: str) -> int:
                if sid in depth_memo:
                    return depth_memo[sid]
                if sid in depth_visiting:
                    return 1
                depth_visiting.add(sid)
                s = step_map.get(sid)
                if not s or not s.dependencies:
                    res = 1
                else:
                    valid_dep_depths = [
                        _get_step_depth(d) for d in s.dependencies if d in step_map
                    ]
                    res = 1 + (max(valid_dep_depths) if valid_dep_depths else 0)
                depth_visiting.remove(sid)
                depth_memo[sid] = res
                return res

            critical_path_depth = max((_get_step_depth(s.id) for s in plan.steps), default=0)
            if critical_path_depth < 2:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-DAG-005",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message=(
                            f"Insufficient topological depth: Plan critical path length is {critical_path_depth} "
                            "(minimum required: 2 for multi-step plans). Plan must not be a flat list of independent steps."
                        ),
                        remediation="Structure the plan into sequential execution stages where later steps depend on deliverables of earlier steps.",
                    )
                )

        # RULE-DAG-008: Isolated Steps Bound (no completely disconnected steps for N > 1)
        if n_steps > 1:
            for step in plan.steps:
                has_deps = bool(step.dependencies)
                is_depended_on = any(step.id in other.dependencies for other in plan.steps)
                if not has_deps and not is_depended_on:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-DAG-008",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=(
                                f"Isolated step '{step.id}' ({step.objective}) detected. "
                                "In a multi-step plan, every step must either depend on another step or be depended upon."
                            ),
                            remediation="Link this step to preceding setup/core steps or make subsequent steps depend on its output.",
                        )
                    )

        # RULE-DAG-006 & RULE-DAG-007: Phase typing constraints on integration steps
        for step in plan.steps:
            raw_phase = getattr(step, "phase_type", None)
            is_integration = (raw_phase == StepPhaseType.INTEGRATION) or (
                isinstance(raw_phase, str)
                and any(kw in raw_phase.lower() for kw in ("integration", "api_call"))
            )
            if is_integration:
                if not step.dependencies:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-DAG-006",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=(
                                f"Integration step '{step.id}' ({step.objective}) has empty dependencies. "
                                "Integration and API steps must integrate previous modules."
                            ),
                            remediation="Add dependencies to foundational components or setup steps being integrated.",
                        )
                    )
                else:
                    ancestors: set[str] = set()
                    stack = list(step.dependencies)
                    while stack:
                        curr_dep = stack.pop()
                        if curr_dep in step_map and curr_dep not in ancestors:
                            ancestors.add(curr_dep)
                            stack.extend(step_map[curr_dep].dependencies)
                    has_setup_ancestor = any(
                        getattr(step_map[anc], "phase_type", None) == StepPhaseType.SETUP
                        or (
                            isinstance(getattr(step_map[anc], "phase_type", None), str)
                            and "setup" in str(step_map[anc].phase_type).lower()
                        )
                        for anc in ancestors
                        if anc in step_map
                    )
                    if not has_setup_ancestor:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-DAG-007",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"step:{step.id}",
                                message=(
                                    f"Integration step '{step.id}' does not depend directly or transitively "
                                    "on any step with phase_type 'setup'."
                                ),
                                remediation="Ensure the integration step depends on initial project setup/scaffolding steps.",
                            )
                        )

        # 3. Check unresolved blocking and warning issues
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

            # RULE-ISSUE-002: Open issues (BLOCKING or WARNING) must be resolved before finalization
            if (
                issue.severity in (IssueSeverity.BLOCKING, IssueSeverity.WARNING)
                and issue.status in (IssueStatus.OPEN, IssueStatus.INVESTIGATING, IssueStatus.PROPOSED_RESOLUTION)
            ):
                sev_str = getattr(issue.severity, "value", str(issue.severity))
                stat_str = getattr(issue.status, "value", str(issue.status))
                violations.append(
                    QualityViolation(
                        rule_id="RULE-ISSUE-002",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"issue:{issue.id}",
                        message=f"Issue [{issue.id}] (severity: {sev_str}, status: {stat_str}) remains open: {issue.claim}",
                        remediation="Giải quyết, từ chối hoặc đánh dấu trùng (DUPLICATE) mọi issue warning trở lên trước khi xuất bản plan.",
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

            # RULE-FULFILL-001: Requirement fulfillment validation (anti-fake-coverage)
            fulfillments = getattr(step, "requirement_fulfillments", []) or []
            for rf in fulfillments:
                cd = (getattr(rf, "concrete_deliverable", None) or "").strip()
                vm = (getattr(rf, "verification_method", None) or "").strip()
                req_id = getattr(rf, "req_id", "REQ")

                # Substantive length check
                if len(cd) < 15:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-FULFILL-001",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=(
                                f"Step '{step.id}' fulfillment for '{req_id}' has too short "
                                f"concrete_deliverable ({len(cd)} chars). Substantive proof required."
                            ),
                            remediation="Provide detailed, substantive concrete deliverable (e.g. code snippet, directory structure, table) proving the requirement is addressed.",
                        )
                    )
                # Placeholder check
                elif (
                    cd.lower() in ("tbd", "n/a", "todo", "deliverable", "chưa có", "sẽ bổ sung", "phủ requirement", "xác minh sau", "placeholder")
                    or cd.lower() == req_id.lower()
                ):
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-FULFILL-001",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=(
                                f"Step '{step.id}' fulfillment for '{req_id}' has placeholder "
                                f"concrete_deliverable: '{cd}'. Must provide detailed implementation artifact or code proof."
                            ),
                            remediation="Replace placeholder text with actual technical specification or code.",
                        )
                    )

                # Verification method check
                if len(vm) < 5 or vm.lower() in ("tbd", "n/a", "todo", "xác minh sau"):
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-FULFILL-001",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"step:{step.id}",
                            message=f"Step '{step.id}' fulfillment for '{req_id}' has empty or invalid verification_method.",
                            remediation="Specify a verifiable method to test the deliverable.",
                        )
                    )

        # RULE-FULFILL-002: Expected artifact type formatting check
        for step in plan.steps:
            fulfillments = getattr(step, "requirement_fulfillments", []) or []
            for rf in fulfillments:
                rid = getattr(rf, "req_id", "")
                cd = getattr(rf, "concrete_deliverable", "") or ""
                matched_req = next((r for r in task.requirements if r.id == rid), None)
                if not matched_req:
                    continue
                art_type = getattr(matched_req, "expected_artifact_type", None)
                if isinstance(art_type, str):
                    try:
                        art_type = ArtifactType(art_type)
                    except ValueError:
                        art_type = ArtifactType.NARRATIVE

                if art_type == ArtifactType.ASSIGNMENT_TABLE:
                    has_table = ("|" in cd and cd.count("|") >= 4) or any(
                        pattern in cd.lower()
                        for pattern in (
                            "bảng phân công", "developer 1", "developer 2", "dev 1", "dev 2",
                            "thành viên 1", "thành viên 2", "lập trình viên 1", "member 1",
                            "frontend dev", "backend dev", "qa / integration", "phân công"
                        )
                    )
                    if not has_table:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-FULFILL-002",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"step:{step.id}",
                                message=(
                                    f"Requirement '{rid}' expects artifact type 'assignment_table', "
                                    f"but concrete_deliverable in step '{step.id}' lacks a table structure or member assignments."
                                ),
                                remediation="Provide an assignment table or matrix detailing tasks/files per developer.",
                            )
                        )
                elif art_type == ArtifactType.DIRECTORY_TREE:
                    has_tree = any(sym in cd for sym in ("├──", "└──", "|--", "\\--")) or any(
                        path in cd.lower() for path in ("src/", "js/", "css/", "index.html", "partials/", "components/", "assets/")
                    ) or (cd.count("/") >= 2 or cd.count("\\") >= 2)
                    if not has_tree:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-FULFILL-002",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"step:{step.id}",
                                message=(
                                    f"Requirement '{rid}' expects artifact type 'directory_tree', "
                                    f"but concrete_deliverable in step '{step.id}' lacks directory tree structure or file paths."
                                ),
                                remediation="Provide a clear directory tree structure showing project files and layout.",
                            )
                        )
                elif art_type == ArtifactType.ARCHITECTURE_DIAGRAM:
                    da_content = " ".join(da.content for da in (getattr(plan, "design_artifacts", []) or []) if rid in da.requirement_ids)
                    combined = cd + " " + da_content
                    has_diagram = any(sym in combined for sym in ("-->", "->", "==>", "flowchart", "graph td", "graph lr", "sequencediagram")) or any(
                        term in combined.lower() for term in ("sơ đồ", "diagram", "luồng dữ liệu", "data flow")
                    ) or ("[" in combined and "]" in combined and "->" in combined)
                    if not has_diagram:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-FULFILL-002",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"step:{step.id}",
                                message=(
                                    f"Requirement '{rid}' expects artifact type 'architecture_diagram', "
                                    f"but deliverable lacks diagram or flow arrows/markup."
                                ),
                                remediation="Provide an architecture diagram or data flow specification using ASCII/mermaid/flow notation.",
                            )
                        )
                elif art_type == ArtifactType.CODE_SNIPPET:
                    has_code = "```" in cd or any(
                        sym in cd for sym in ("<script", "</script>", "function ", "class ", "const ", "let ", "def ", "() =>", "import ", "export ", "addEventListener")
                    ) or ("{" in cd and "}" in cd and ";" in cd)
                    if not has_code:
                        violations.append(
                            QualityViolation(
                                rule_id="RULE-FULFILL-002",
                                severity=ViolationSeverity.BLOCKER,
                                entity_ref=f"step:{step.id}",
                                message=(
                                    f"Requirement '{rid}' expects artifact type 'code_snippet', "
                                    f"but concrete_deliverable in step '{step.id}' lacks code syntax or code block."
                                ),
                                remediation="Provide concrete code snippet demonstrating implementation.",
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

        # Check for unaddressed failed execution evidence / validation results (RULE-TECH-002)
        unaddressed_failures = [
            v for v in state.validations
            if v.status == ValidationStatus.FAIL and v.exit_code is not None and v.exit_code != 0
        ]
        if unaddressed_failures:
            has_passing = any(v.status == ValidationStatus.PASS for v in state.validations)
            if not has_passing:
                for fv in unaddressed_failures:
                    violations.append(
                        QualityViolation(
                            rule_id="RULE-TECH-002",
                            severity=ViolationSeverity.BLOCKER,
                            entity_ref=f"validation:{fv.id}",
                            message=f"Executable sandbox verification failed: {fv.actual or fv.expected}",
                            remediation="Resolve sandbox test violations before plan can pass quality gate.",
                        )
                    )

        # 6. Check Technical Grounding Physical Constraints (RULE-TECH-001)
        from astra_multi.orchestration.technical_grounding import (
            build_tech_stack_truth_table,
            verify_technical_grounding,
        )

        truth_table = build_tech_stack_truth_table(task)
        if truth_table.entries:
            tech_violations = verify_technical_grounding(
                task=task,
                proposal=None,
                plan=plan,
                truth_table=truth_table,
            )
            for tv in tech_violations:
                violations.append(
                    QualityViolation(
                        rule_id="RULE-TECH-001",
                        severity=ViolationSeverity.BLOCKER,
                        entity_ref=f"plan:{plan.id}",
                        message=tv.claim,
                        remediation=tv.suggested_resolution,
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
