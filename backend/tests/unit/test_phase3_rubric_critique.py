"""Tests for Phase 3: Rubric-Driven Critique & Reviewer Constraints.

Covers:
1. Automatic generation of EvaluationRubric / RubricChecklist at INTAKE.
2. ReviewOutput schema with Part 1 (rubric_audits) and Part 2 (constraint_audits).
3. Auto-elevation of MISSING/PARTIAL rubric audits to BLOCKING issues.
4. Auto-elevation of conflict_detected constraint audits to BLOCKING issues.
5. Out-of-Scope Issue Filter: issues lacking valid requirement_ids or demanding
   unrequested state management (Redux, Zustand) downgraded to NITPICK.
6. NITPICK issues do not block Quality Gate or finalization.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from astra_multi.agents.roles import (
    ConstraintAuditItem,
    IssueReport,
    ProposalOutput,
    ReviewOutput,
    RubricAuditItem,
)
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    ArtifactType,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    RequirementType,
    RubricChecklist,
    RubricItem,
    RunPhase,
    RunStatus,
    StepPhaseType,
    TaskSpec,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
from astra_multi.orchestration.budget import BudgetService
from astra_multi.context.bundle import ContextBuilder
from astra_multi.orchestration.contract_extractor import generate_evaluation_rubric
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


def test_generate_evaluation_rubric():
    task = TaskSpec(
        id="TASK-001",
        revision=1,
        goal="Test app",
        requirements=[
            Requirement(
                id="REQ-TECH-001",
                text="Chạy trực tiếp file:// không bundler",
                acceptance="Mở được bằng trình duyệt",
                req_type=RequirementType.TECH,
                acceptance_criteria=[
                    "Không dùng bundler hay build step",
                    "Chạy qua giao thức file://",
                ],
            ),
            Requirement(
                id="REQ-DELIV-001",
                text="Giải pháp tái sử dụng Header/Footer",
                acceptance="Có cơ chế nạp layout",
                req_type=RequirementType.DELIV,
                expected_artifact_type=ArtifactType.CODE_SNIPPET,
                acceptance_criteria=["Có code mẫu fetch hoặc template load header/footer"],
                verifiable_deliverable="code_snippet",
            ),
            Requirement(
                id="REQ-ORG-001",
                text="Bảng phân công 4 thành viên",
                acceptance="Phân chia rõ ràng không xung đột",
                req_type=RequirementType.ORG,
                expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
                acceptance_criteria=["Phân công đủ 4 thành viên độc lập"],
                verifiable_deliverable="assignment_table",
            ),
        ],
    )

    rubric = generate_evaluation_rubric(task)
    assert isinstance(rubric, RubricChecklist)
    assert len(rubric.items) == 4

    item_ids = [item.rubric_id for item in rubric.items]
    assert "RUBRIC-REQ-TECH-001-1" in item_ids
    assert "RUBRIC-REQ-TECH-001-2" in item_ids
    assert "RUBRIC-REQ-DELIV-001-1" in item_ids
    assert "RUBRIC-REQ-ORG-001-1" in item_ids

    # Categories
    tech_items = [i for i in rubric.items if i.category == "TECH"]
    deliv_items = [i for i in rubric.items if i.category == "DELIV"]
    org_items = [i for i in rubric.items if i.category == "ORG"]
    assert len(tech_items) == 2
    assert len(deliv_items) == 1
    assert len(org_items) == 1


def test_review_output_schema_with_rubrics_and_constraints():
    out = ReviewOutput(
        summary="Review with rubric and constraint audits",
        rubric_audits=[
            RubricAuditItem(
                rubric_id="RUBRIC-REQ-DELIV-001-1",
                req_id="REQ-DELIV-001",
                status="MET",
                evidence_quote="STEP-002 lines 10-15 fetch partials",
                notes="Layout partial mechanism demonstrated",
            ),
            RubricAuditItem(
                rubric_id="RUBRIC-REQ-ORG-001-1",
                req_id="REQ-ORG-001",
                status="MISSING",
                evidence_quote="",
                notes="Missing 4-member assignment table",
            ),
        ],
        constraint_audits=[
            ConstraintAuditItem(
                tech_req_id="REQ-TECH-001",
                solution_analyzed="Using ES Module import in index.html",
                conflict_detected=True,
                conflict_details="ES modules fail with CORS policy when loaded directly via file://",
                suggested_fix="Use classic script tags instead of ES modules",
            )
        ],
        issues=[],
    )
    assert len(out.rubric_audits) == 2
    assert out.rubric_audits[1].status == "MISSING"
    assert len(out.constraint_audits) == 1
    assert out.constraint_audits[0].conflict_detected is True


def test_auto_elevation_and_out_of_scope_filter_in_review_node():
    """Verify in review_node:
    1. MISSING/PARTIAL rubric audit becomes BLOCKING issue.
    2. conflict_detected constraint audit becomes BLOCKING issue.
    3. Issue without requirement_ids or demanding unrequested Redux/Zustand becomes NITPICK.
    """
    recorded_issues: list[Issue] = []

    def mock_adapter(role: str, messages: list[dict], output_schema: type, **kwargs):
        if output_schema == ReviewOutput:
            content = ReviewOutput(
                summary="Review with rubric audits and issues",
                rubric_audits=[
                    RubricAuditItem(
                        rubric_id="RUBRIC-REQ-DELIV-001-1",
                        req_id="REQ-DELIV-001",
                        status="MISSING",
                        notes="No header/footer layout loader found",
                    )
                ],
                constraint_audits=[
                    ConstraintAuditItem(
                        tech_req_id="REQ-TECH-001",
                        solution_analyzed="import './api.js' in index.html",
                        conflict_detected=True,
                        conflict_details="ES modules blocked on file:// protocol",
                        suggested_fix="Use script tags",
                    )
                ],
                issues=[
                    # Issue 1: Valid requirement link
                    IssueReport(
                        claim="API service lacks error handling for MockAPI 429",
                        impact="User receives silent failure on rate limit",
                        severity=IssueSeverity.WARNING,
                        suggested_resolution="Add retry or user toast",
                        requirement_ids=["REQ-TECH-001"],
                    ),
                    # Issue 2: Unrequested Redux recommendation (Out-of-Scope)
                    IssueReport(
                        claim="State should be managed via Redux Toolkit and Zustand store slices",
                        impact="Architecture lacks centralized unidirectional store",
                        severity=IssueSeverity.BLOCKING,
                        suggested_resolution="Introduce Redux store slice and action creators",
                        requirement_ids=["REQ-TECH-001"],
                    ),
                    # Issue 3: Completely unmapped issue (No requirement_ids)
                    IssueReport(
                        claim="Consider dark mode CSS custom properties for future themes",
                        impact="Low visual adaptability",
                        severity=IssueSeverity.WARNING,
                        suggested_resolution="Define CSS root vars for colors",
                        requirement_ids=[],
                    ),
                ],
            )
            return ModelResult(
                content=content.model_dump(mode="json"),
                model_id="mock-reviewer",
                provider="mock",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                cost_actual_usd=0.0,
            )
        return ModelResult(
            content={"approach": "Default proposal"},
            model_id="mock-planner",
            provider="mock",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.0,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            task = TaskSpec(
                id=state.task.id,
                revision=1,
                goal="Static web app without bundler",
                requirements=[
                    Requirement(
                        id="REQ-TECH-001",
                        text="Chạy trên file:// không dùng bundler",
                        acceptance="Mở được trên browser",
                        req_type=RequirementType.TECH,
                    ),
                    Requirement(
                        id="REQ-DELIV-001",
                        text="Tái sử dụng layout Header/Footer",
                        acceptance="Nạp layout partial",
                        req_type=RequirementType.DELIV,
                    ),
                ],
            )
            store.create(task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-owner", ttl=300)
            controller = WorkflowController(store, lease, actor="test-owner")
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=mock_adapter)
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Transition through phases up to PROPOSE so REVIEW transition is valid
            controller.transition_phase(RunPhase.SNAPSHOT)
            controller.transition_phase(RunPhase.INVESTIGATE)
            controller.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
            controller.transition_phase(RunPhase.PROPOSE)

            # Run review node
            prop_state = {
                "run_id": state.run.id,
                "round": 0,
                "proposal": ProposalOutput(approach="Vanilla JS architecture").model_dump(mode="json"),
                "events": [],
            }
            nodes = {node[0]: node[1] for node in graph.nodes.items()}
            review_func = nodes["review"].runnable.func

            res = review_func(prop_state)
            assert "review" in res

            # Inspect issues recorded in domain store
            recorded = store.load(state.run.id).issues

            # 1. Rubric MISSING became BLOCKING
            rubric_issue = next((i for i in recorded if "RUBRIC-REQ-DELIV-001-1" in i.claim), None)
            assert rubric_issue is not None
            assert rubric_issue.severity == IssueSeverity.BLOCKING

            # 2. Constraint conflict became BLOCKING
            conflict_issue = next((i for i in recorded if "Constraint conflict with REQ-TECH-001" in i.claim), None)
            assert conflict_issue is not None
            assert conflict_issue.severity == IssueSeverity.BLOCKING

            # 3. Legitimate API error remained WARNING
            api_issue = next((i for i in recorded if "MockAPI 429" in i.claim), None)
            assert api_issue is not None
            assert api_issue.severity == IssueSeverity.WARNING

            # 4. Out-of-scope Redux suggestion was downgraded to NITPICK
            redux_issue = next((i for i in recorded if "Redux Toolkit" in i.claim), None)
            assert redux_issue is not None
            assert redux_issue.severity == IssueSeverity.NITPICK

            # 5. Unmapped issue without requirement_ids was downgraded to NITPICK
            darkmode_issue = next((i for i in recorded if "dark mode" in i.claim), None)
            assert darkmode_issue is not None
            assert darkmode_issue.severity == IssueSeverity.NITPICK


def test_nitpick_issues_do_not_block_quality_validator():
    """Verify that NITPICK issues do not trigger RULE-ISSUE-001 or RULE-ISSUE-002."""
    state = sample_state(repo=False)
    nitpick_issue = Issue(
        id="ISSUE-NIT-001",
        run_id=state.run.id,
        based_on_revision=0,
        severity=IssueSeverity.NITPICK,
        status=IssueStatus.OPEN,
        claim="Consider adding code comments for CSS helpers",
        impact="Low readability",
        verification_request="Check comments",
        suggested_resolution="Add comments",
        requirement_ids=["REQ-001"],
    )
    state.issues.append(nitpick_issue)

    step1 = PlanStep(
        id="STEP-001",
        phase_type=StepPhaseType.SETUP,
        objective="Project scaffolding",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-001",
                fulfilled_by_section="Scaffolding",
                concrete_deliverable="Detailed directory tree with index.html and shared css",
                verification_method="Verify file tree on disk",
            )
        ],
        dependencies=[],
        targets=["index.html"],
        validation="test",
        deliverables=["index.html"],
        completion_criteria=["ready"],
    )
    step2 = PlanStep(
        id="STEP-002",
        phase_type=StepPhaseType.CORE_MODULE,
        objective="Core implementation",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-001",
                fulfilled_by_section="Core logic",
                concrete_deliverable="Concrete JS implementation with event bindings",
                verification_method="Verify functionality in browser",
            )
        ],
        dependencies=["STEP-001"],
        targets=["app.js"],
        validation="test",
        deliverables=["app.js"],
        completion_criteria=["ready"],
    )

    plan = PlanRevision(
        id="PLAN-001",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2],
    )
    state.plans.append(plan)

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    # There should be no BLOCKER violations from ISSUE-NIT-001
    issue_violations = [v for v in report.violations if "RULE-ISSUE" in v.rule_id]
    assert len(issue_violations) == 0
    assert report.passed is True
