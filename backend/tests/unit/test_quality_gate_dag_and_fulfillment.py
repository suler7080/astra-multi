"""Unit tests for Phase 2: DAG Invariants, Requirement Fulfillment, and Semantic Rubric Checker."""

from __future__ import annotations

from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    ArtifactType,
    AssignmentMatrix,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    RequirementType,
    StepPhaseType,
    TaskSpec,
    WorkerAssignment,
)
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
)
from astra_multi.orchestration.rubric_checker import evaluate_semantic_rubrics


def create_step(
    step_id: str,
    req_ids: list[str],
    dependencies: list[str] = None,
    phase_type: StepPhaseType = StepPhaseType.CORE_MODULE,
    deliverable: str = "Detailed technical deliverable implementation component",
    validation: str = "pytest tests/test_component.py",
) -> PlanStep:
    fulfillments = [
        RequirementFulfillment(
            req_id=rid,
            fulfilled_by_section=f"Section for {step_id}",
            concrete_deliverable=deliverable,
            verification_method=validation,
        )
        for rid in req_ids
    ]
    return PlanStep(
        id=step_id,
        objective=f"Objective for {step_id}",
        phase_type=phase_type,
        requirement_fulfillments=fulfillments,
        requirement_ids=req_ids,
        dependencies=dependencies or [],
        validation=validation,
        deliverables=[deliverable],
        completion_criteria=["Verifiable completion criteria satisfied"],
    )


# ---------------------------------------------------------------------------
# Test DAG Invariants (RULE-DAG-003, RULE-DAG-004, RULE-DAG-005, 006, 007)
# ---------------------------------------------------------------------------


def test_rule_dag_003_fails_disconnected_graph():
    """RULE-DAG-003: Multi-step plan with edges < N - 1 must fail as disconnected graph."""
    state = sample_state()
    # 3 steps, but only 1 edge (STEP-2 -> STEP-1), while STEP-3 is disconnected. Total edges = 1 < 3 - 1 = 2
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=["STEP-1"], phase_type=StepPhaseType.CORE_MODULE)
    step3 = create_step("STEP-3", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.CORE_MODULE)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2, step3],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-DAG-003" for v in report.violations)


def test_rule_dag_004_fails_excessive_roots():
    """RULE-DAG-004: Plan with N >= 3 and > 2 roots without dependencies must fail."""
    state = sample_state()
    # 4 steps: 3 roots (STEP-1, STEP-2, STEP-3) and STEP-4 depends on all 3.
    # Total edges = 3 (>= 4 - 1), but roots = 3 (> 2).
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step3 = create_step("STEP-3", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.CORE_MODULE)
    step4 = create_step("STEP-4", ["REQ-001"], dependencies=["STEP-1", "STEP-2", "STEP-3"], phase_type=StepPhaseType.VERIFICATION)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2, step3, step4],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-DAG-004" for v in report.violations)


def test_rule_dag_005_fails_insufficient_depth():
    """RULE-DAG-005: Multi-step plan with critical path length < 2 must fail."""
    state = sample_state()
    # 2 steps with no dependencies: depth = 1 < 2
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.CORE_MODULE)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-DAG-005" for v in report.violations)


def test_rule_dag_006_fails_integration_step_empty_dependencies():
    """RULE-DAG-006: Integration step must not have empty dependencies."""
    state = sample_state()
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.INTEGRATION)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-DAG-006" for v in report.violations)


def test_rule_dag_007_fails_integration_without_setup_ancestor():
    """RULE-DAG-007: Integration step must transitively depend on a step with phase_type 'setup'."""
    state = sample_state()
    # STEP-1 is core_module, STEP-2 is integration depending on STEP-1. No setup step exists!
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.CORE_MODULE)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=["STEP-1"], phase_type=StepPhaseType.INTEGRATION)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-DAG-007" for v in report.violations)


def test_valid_dag_and_phases_passes_all_dag_rules():
    """Valid DAG with setup -> core_module -> integration -> verification passes all DAG rules."""
    state = sample_state()
    step1 = create_step("STEP-1", ["REQ-001"], dependencies=[], phase_type=StepPhaseType.SETUP)
    step2 = create_step("STEP-2", ["REQ-001"], dependencies=["STEP-1"], phase_type=StepPhaseType.CORE_MODULE)
    step3 = create_step("STEP-3", ["REQ-001"], dependencies=["STEP-2"], phase_type=StepPhaseType.INTEGRATION)
    step4 = create_step("STEP-4", ["REQ-001"], dependencies=["STEP-3"], phase_type=StepPhaseType.VERIFICATION)

    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2, step3, step4],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is True
    assert not any(v.rule_id.startswith("RULE-DAG-") for v in report.violations)


# ---------------------------------------------------------------------------
# Test Requirement Fulfillment (RULE-FULFILL-001)
# ---------------------------------------------------------------------------


def test_rule_fulfill_001_fails_placeholder_deliverable():
    """RULE-FULFILL-001: Placeholder or empty concrete deliverable must fail."""
    state = sample_state()
    bad_rf = RequirementFulfillment(
        req_id="REQ-001",
        fulfilled_by_section="Section 1",
        concrete_deliverable="TBD",
        verification_method="pytest tests/",
    )
    step = PlanStep(
        id="STEP-1",
        objective="Initial step",
        phase_type=StepPhaseType.SETUP,
        requirement_fulfillments=[bad_rf],
        requirement_ids=["REQ-001"],
        dependencies=[],
        validation="pytest tests/",
        deliverables=["code implementation component"],
        completion_criteria=["tests pass"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-FULFILL-001" for v in report.violations)


def test_rule_fulfill_001_fails_too_short_deliverable():
    """RULE-FULFILL-001: Too short concrete deliverable (< 15 chars) must fail."""
    state = sample_state()
    bad_rf = RequirementFulfillment(
        req_id="REQ-001",
        fulfilled_by_section="Section 1",
        concrete_deliverable="small",
        verification_method="pytest tests/",
    )
    step = PlanStep(
        id="STEP-1",
        objective="Initial step",
        phase_type=StepPhaseType.SETUP,
        requirement_fulfillments=[bad_rf],
        requirement_ids=["REQ-001"],
        dependencies=[],
        validation="pytest tests/",
        deliverables=["code implementation component"],
        completion_criteria=["tests pass"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )
    state = state.model_copy(update={"plans": [plan]})
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert not report.passed
    assert any(v.rule_id == "RULE-FULFILL-001" for v in report.violations)


# ---------------------------------------------------------------------------
# Test Semantic Rubric Checker (evaluate_semantic_rubrics)
# ---------------------------------------------------------------------------


def test_rubric_checker_fails_fake_assignment_table():
    """Rubric checker fails when 4-member assignment only mentions vague commitment without matrix/roles."""
    task = TaskSpec(
        id="TASK-1",
        goal="Build application with 4 members",
        requirements=[
            Requirement(
                id="REQ-ORG-001",
                text="Phân công công việc cho đúng 4 lập trình viên không chồng chéo file",
                acceptance="Bảng phân công 4 thành viên độc lập",
                req_type=RequirementType.ORG,
                expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
            )
        ],
    )
    # Step has superficial statement: "4 thành viên commit lên thư mục riêng"
    step = PlanStep(
        id="STEP-1",
        objective="Team management",
        phase_type=StepPhaseType.SETUP,
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-ORG-001",
                fulfilled_by_section="Team assignment",
                concrete_deliverable="4 thành viên commit lên thư mục riêng độc lập",
                verification_method="Check git commits",
            )
        ],
        requirement_ids=["REQ-ORG-001"],
        dependencies=[],
        validation="Check git commits",
        deliverables=["Team repository setup"],
        completion_criteria=["Commits verified"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )

    verdicts = evaluate_semantic_rubrics(task, plan)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "FAIL"
    assert "does not contain one" in verdicts[0].gap
    assert "RULE-ASSIGN-001" in verdicts[0].gap


def test_rubric_checker_passes_concrete_assignment_table():
    """Rubric checker passes when an explicit role assignment table is provided."""
    task = TaskSpec(
        id="TASK-1",
        goal="Build application with 4 members",
        requirements=[
            Requirement(
                id="REQ-ORG-001",
                text="Phân công công việc cho đúng 4 lập trình viên không chồng chéo file",
                acceptance="Bảng phân công 4 thành viên độc lập",
                req_type=RequirementType.ORG,
                expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
            )
        ],
    )
    assignments = [
        ("frontend-ui", "Frontend UI", ["js/ui.js", "css/app.css"]),
        ("api-state", "API & State", ["js/api.js", "js/state.js"]),
        ("layout-router", "Layout & Router", ["js/layout.js", "partials/"]),
        ("qa-integration", "QA & Integration", ["tests/", "integration.js"]),
    ]
    steps = [
        PlanStep(
            id=f"STEP-{index}",
            objective=f"{role} ownership for {', '.join(files)}",
            phase_type=StepPhaseType.SETUP,
            requirement_fulfillments=[
                RequirementFulfillment(
                    req_id="REQ-ORG-001",
                    fulfilled_by_section=f"{role} ownership",
                    concrete_deliverable=(
                        f"{role} owns {', '.join(files)} and no other worker "
                        "modifies those files."
                    ),
                    verification_method="Audit file ownership across 4 roles",
                )
            ],
            requirement_ids=["REQ-ORG-001"],
            dependencies=[],
            validation="Audit file ownership",
            deliverables=[f"{role} implementation"],
            completion_criteria=["Matrix verified"],
            worker_role=role,
            owned_files=list(files),
        )
        for index, (role, _name, files) in enumerate(assignments, start=1)
    ]
    matrix = AssignmentMatrix(
        workers=[
            WorkerAssignment(
                worker_role=role,
                display_name=name,
                responsibilities=[f"Own {', '.join(files)}"],
                owned_files=list(files),
                requirement_ids=["REQ-ORG-001"],
                step_ids=[f"STEP-{index}"],
            )
            for index, (role, name, files) in enumerate(assignments, start=1)
        ],
        expected_worker_count=4,
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=steps,
        assignment_matrix=matrix,
    )

    verdicts = evaluate_semantic_rubrics(task, plan)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "PASS"


def test_rubric_checker_fails_org_matrix_with_unowned_step():
    """An ORG PASS is invalid when any step has no worker or owned files."""
    task = TaskSpec(
        id="TASK-1",
        goal="Build application",
        requirements=[
            Requirement(
                id="REQ-ORG-001",
                text="Bảng phân công nhiệm vụ cho từng thành viên",
                acceptance="Mọi bước đều có người phụ trách và file sở hữu",
                req_type=RequirementType.ORG,
                expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
            )
        ],
    )
    step = PlanStep(
        id="STEP-1",
        objective="Unassigned work",
        requirement_ids=["REQ-ORG-001"],
        dependencies=[],
        validation="Audit ownership",
        deliverables=["module"],
        completion_criteria=["Ownership verified"],
    )
    matrix = AssignmentMatrix(
        workers=[
            WorkerAssignment(
                worker_role="api",
                display_name="API",
                responsibilities=["Own the API module"],
                owned_files=["src/api.py"],
                requirement_ids=["REQ-ORG-001"],
                step_ids=[],
            )
        ],
        expected_worker_count=1,
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
        assignment_matrix=matrix,
    )

    verdicts = evaluate_semantic_rubrics(task, plan)

    assert len(verdicts) == 1
    assert verdicts[0].verdict == "FAIL"
    assert "RULE-ASSIGN-008" in verdicts[0].gap


def test_rubric_checker_fails_missing_layout_solution():
    """Rubric checker fails when reusable layout lacks technical loading mechanism or code."""
    task = TaskSpec(
        id="TASK-1",
        goal="Multi-page web application",
        requirements=[
            Requirement(
                id="REQ-DELIV-001",
                text="Giải pháp tái sử dụng layout Header/Footer khi không dùng SPA framework",
                acceptance="Header và footer dùng chung trên các trang",
                req_type=RequirementType.DELIV,
                expected_artifact_type=ArtifactType.CODE_SNIPPET,
            )
        ],
    )
    step = PlanStep(
        id="STEP-1",
        objective="Layout setup",
        phase_type=StepPhaseType.SETUP,
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-DELIV-001",
                fulfilled_by_section="Layout",
                concrete_deliverable="Có giải pháp layout header footer dùng chung cho các trang",
                verification_method="Mở trình duyệt kiểm tra",
            )
        ],
        requirement_ids=["REQ-DELIV-001"],
        dependencies=[],
        validation="Mở trình duyệt kiểm tra",
        deliverables=["Layout template"],
        completion_criteria=["Pages render correctly"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )

    verdicts = evaluate_semantic_rubrics(task, plan)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "FAIL"
    assert "Thiếu giải pháp kỹ thuật cụ thể" in verdicts[0].gap


def test_rubric_checker_passes_concrete_layout_solution():
    """Rubric checker passes when fetch/partial loading code snippet is provided."""
    task = TaskSpec(
        id="TASK-1",
        goal="Multi-page web application",
        requirements=[
            Requirement(
                id="REQ-DELIV-001",
                text="Giải pháp tái sử dụng layout Header/Footer khi không dùng SPA framework",
                acceptance="Header và footer dùng chung trên các trang",
                req_type=RequirementType.DELIV,
                expected_artifact_type=ArtifactType.CODE_SNIPPET,
            )
        ],
    )
    layout_code = (
        "Cơ chế load partial layout bằng Vanilla JS fetch:\n"
        "```javascript\n"
        "async function loadLayout() {\n"
        "  const headerResp = await fetch('partials/header.html');\n"
        "  document.getElementById('header-container').innerHTML = await headerResp.text();\n"
        "  const footerResp = await fetch('partials/footer.html');\n"
        "  document.getElementById('footer-container').innerHTML = await footerResp.text();\n"
        "}\n"
        "```"
    )
    step = PlanStep(
        id="STEP-1",
        objective="Reusable layout implementation",
        phase_type=StepPhaseType.SETUP,
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-DELIV-001",
                fulfilled_by_section="Layout partial loader",
                concrete_deliverable=layout_code,
                verification_method="Verify header and footer partials fetch on index.html",
            )
        ],
        requirement_ids=["REQ-DELIV-001"],
        dependencies=[],
        validation="Verify layout partials fetch on index.html",
        deliverables=["partials/header.html", "partials/footer.html", "js/layout.js"],
        completion_criteria=["Layout loads dynamically on all pages"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )

    verdicts = evaluate_semantic_rubrics(task, plan)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "PASS"
