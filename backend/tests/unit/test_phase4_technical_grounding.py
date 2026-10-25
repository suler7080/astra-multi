"""Unit tests for Phase 4: Technical Grounding at INVESTIGATE and VERIFY."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from astra_multi.agents.roles import ProposalOutput, ReviewOutput
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    RequirementType,
    RunPhase,
    RunStatus,
    StepPhaseType,
    TaskSpec,
)
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
    ViolationSeverity,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.orchestration.technical_grounding import (
    build_tech_stack_truth_table,
    is_negated_or_prohibition,
    verify_technical_grounding,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


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
# 1. Truth Table Generation Tests
# ---------------------------------------------------------------------------


def test_build_tech_stack_truth_table_greenfield_web():
    """Verify that build_tech_stack_truth_table extracts all 4 constraints from a web static task."""
    task = TaskSpec(
        id="TASK-WEB-001",
        revision=1,
        goal="Xây dựng ứng dụng web tĩnh tuyển dụng không dùng framework, mở trực tiếp qua file://, kết nối MockAPI và có tính năng chat tin nhắn.",
        requirements=[
            Requirement(
                id="REQ-TECH-001",
                text="Chạy trực tiếp trên trình duyệt qua file:// không dùng web server hay bundler",
                req_type=RequirementType.TECH,
                acceptance="Double click index.html mở được",
                acceptance_criteria=["Double click index.html mở được"],
            ),
            Requirement(
                id="REQ-TECH-002",
                text="Sử dụng MockAPI.io làm backend RESTful API",
                req_type=RequirementType.TECH,
                acceptance="Lưu trữ tin nhắn và ứng viên trên MockAPI",
                acceptance_criteria=["Lưu trữ tin nhắn và ứng viên trên MockAPI"],
            ),
            Requirement(
                id="REQ-DELIV-001",
                text="Giải pháp tái sử dụng Header/Footer cho các trang HTML",
                req_type=RequirementType.DELIV,
                acceptance="Không trùng lặp mã nguồn giao diện",
                acceptance_criteria=["Không trùng lặp mã nguồn giao diện"],
            ),
            Requirement(
                id="REQ-DELIV-002",
                text="Module chat tin nhắn trực tiếp giữa ứng viên và nhà tuyển dụng",
                req_type=RequirementType.DELIV,
                acceptance="Gửi nhận tin nhắn không bị lag hoặc reload trang",
                acceptance_criteria=["Gửi nhận tin nhắn không bị lag hoặc reload trang"],
            ),
        ],
        constraints=[
            "Không dùng framework SPA (React, Vue, Angular)",
            "Không có bước build (no build step), dùng đường dẫn tương đối",
        ],
    )

    truth_table = build_tech_stack_truth_table(task)
    tech_ids = {e.tech_id for e in truth_table.entries}

    assert "TECH-FILE-PROTOCOL" in tech_ids
    assert "TECH-MOCKAPI" in tech_ids
    assert "TECH-REALTIME-CHAT" in tech_ids
    assert "TECH-NO-BUILD" in tech_ids

    file_entry = next(e for e in truth_table.entries if e.tech_id == "TECH-FILE-PROTOCOL")
    assert "Origin: null" in file_entry.physical_limitation
    assert "layout.js" in file_entry.mandated_pattern
    assert any("fetch('header.html')" in p for p in file_entry.prohibited_patterns)

    mockapi_entry = next(e for e in truth_table.entries if e.tech_id == "TECH-MOCKAPI")
    assert "không có khả năng sinh JWT" in mockapi_entry.physical_limitation
    assert "sessionStorage/localStorage" in mockapi_entry.mandated_pattern

    chat_entry = next(e for e in truth_table.entries if e.tech_id == "TECH-REALTIME-CHAT")
    assert "location.reload()" in chat_entry.prohibited_patterns


def test_build_tech_stack_truth_table_unrelated_task():
    """Unrelated tasks (like backend algorithms) should not trigger web constraints."""
    task = TaskSpec(
        id="TASK-ALGO-001",
        revision=1,
        goal="Implement deterministic Mersenne Twister PRNG in pure Python",
        requirements=[
            Requirement(id="REQ-001", text="Grid allocation algorithm", acceptance="passes", acceptance_criteria=["passes"]),
        ],
    )
    truth_table = build_tech_stack_truth_table(task)
    assert len(truth_table.entries) == 0


# ---------------------------------------------------------------------------
# 2. Pattern Verification & Negation Handling Tests
# ---------------------------------------------------------------------------


def test_verify_technical_grounding_detects_violations():
    """Verify that prohibited patterns in proposal and plan steps are detected."""
    task = TaskSpec(
        id="TASK-WEB-001",
        revision=1,
        goal="Web tĩnh mở qua file://, dùng MockAPI, có chat tin nhắn, không có build",
        requirements=[
            Requirement(id="REQ-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
            Requirement(id="REQ-002", text="Kết nối MockAPI", req_type=RequirementType.TECH, acceptance="pass"),
            Requirement(id="REQ-003", text="Chat tin nhắn", req_type=RequirementType.DELIV, acceptance="pass"),
        ],
    )

    # Flawed proposal violating all constraints
    flawed_proposal = ProposalOutput(
        approach=(
            "Tái sử dụng layout bằng fetch('header.html') vào index.html. "
            "Người dùng đăng nhập thì MockAPI sinh JWT token gửi về client. "
            "Khi gửi tin nhắn trong chat, gọi window.location.reload() để cập nhật tin nhắn mới."
        ),
        alternatives=["Dùng thư mục build/ để lưu mã nguồn"],
        tradeoffs=["Tải lại trang làm trắng màn hình một lát nhưng đơn giản"],
        requirement_coverage={"REQ-001": "Dùng type='module' để import api from './api.js'"},
        claim_ids=[],
    )

    violations = verify_technical_grounding(task, proposal=flawed_proposal, plan=None)
    violation_tech_ids = {v.tech_id for v in violations}

    assert "TECH-FILE-PROTOCOL" in violation_tech_ids
    assert "TECH-MOCKAPI" in violation_tech_ids
    assert "TECH-REALTIME-CHAT" in violation_tech_ids
    assert "TECH-NO-BUILD" in violation_tech_ids

    for v in violations:
        assert v.severity == IssueSeverity.BLOCKING
        assert len(v.suggested_resolution) > 10


def test_is_negated_or_prohibition_safety():
    """Ensure explicit prohibitions (e.g. 'cấm window.location.reload()') are not falsely flagged."""
    text1 = "Lưu ý quan trọng: Tuyệt đối không dùng window.location.reload() sau khi gửi tin nhắn."
    pos1 = text1.find("window.location.reload()")
    assert is_negated_or_prohibition(text1, pos1) is True

    text2 = "Tránh sử dụng fetch('header.html') vì sẽ bị lỗi CORS trên file://."
    pos2 = text2.find("fetch('header.html')")
    assert is_negated_or_prohibition(text2, pos2) is True

    text3 = "Thực hiện gọi window.location.reload() để tải lại danh sách tin nhắn."
    pos3 = text3.find("window.location.reload()")
    assert is_negated_or_prohibition(text3, pos3) is False


# ---------------------------------------------------------------------------
# 3. StructuralQualityValidator RULE-TECH-001 Tests
# ---------------------------------------------------------------------------


def test_structural_quality_validator_rule_tech_001_catches_violations():
    """StructuralQualityValidator must fail with RULE-TECH-001 if plan contains physical violations."""
    task = TaskSpec(
        id="TASK-WEB-001",
        revision=1,
        goal="Ứng dụng web mở file:// trực tiếp, không bundler, có chat tin nhắn",
        requirements=[
            Requirement(id="REQ-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
            Requirement(id="REQ-002", text="Chat tin nhắn", req_type=RequirementType.DELIV, acceptance="pass"),
        ],
    )

    flawed_step = create_step(
        step_id="STEP-1",
        req_ids=["REQ-001", "REQ-002"],
        deliverable="Module chat gọi location.reload() sau mỗi tin nhắn và dùng fetch('header.html')",
        validation="Kiểm tra mở trình duyệt",
    )
    base_state = sample_state(repo=False)
    plan = PlanRevision(
        id="PLAN-1",
        run_id=base_state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[flawed_step],
        decisions=[],
        risks=[],
    )
    state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    assert report.passed is False
    tech_violations = [v for v in report.violations if v.rule_id == "RULE-TECH-001"]
    assert len(tech_violations) > 0
    assert any("TECH-FILE-PROTOCOL" in v.message or "TECH-REALTIME-CHAT" in v.message for v in tech_violations)


def test_structural_quality_validator_passes_when_grounded():
    """StructuralQualityValidator passes when plan uses grounded patterns."""
    task = TaskSpec(
        id="TASK-WEB-001",
        revision=1,
        goal="Ứng dụng web mở file:// trực tiếp, không bundler, có chat tin nhắn",
        requirements=[
            Requirement(id="REQ-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
            Requirement(id="REQ-002", text="Chat tin nhắn", req_type=RequirementType.DELIV, acceptance="pass"),
        ],
    )

    step_setup = create_step(
        step_id="STEP-1",
        req_ids=["REQ-001"],
        phase_type=StepPhaseType.SETUP,
        deliverable="Tệp js/layout.js tiêm header/footer vào DOM qua script defer không dùng fetch",
        validation="Mở index.html kiểm tra header hiển thị đầy đủ",
    )
    step_chat = create_step(
        step_id="STEP-2",
        req_ids=["REQ-002"],
        dependencies=["STEP-1"],
        phase_type=StepPhaseType.INTEGRATION,
        deliverable="Module chat cập nhật DOM trực tiếp qua appendChild sau khi POST bất đồng bộ",
        validation="Gửi tin nhắn và kiểm tra DOM cập nhật không reload trang",
    )
    step_verif = create_step(
        step_id="STEP-3",
        req_ids=["REQ-001", "REQ-002"],
        dependencies=["STEP-2"],
        phase_type=StepPhaseType.VERIFICATION,
        deliverable="Kiểm thử tích hợp end-to-end trên trình duyệt không lỗi CORS",
        validation="Kiểm tra console không có lỗi CORS và tin nhắn hiển thị đúng",
    )

    base_state = sample_state(repo=False)
    plan = PlanRevision(
        id="PLAN-1",
        run_id=base_state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step_setup, step_chat, step_verif],
        decisions=[],
        risks=[],
    )
    state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})

    validator = StructuralQualityValidator()
    report = validator.validate(state)

    tech_violations = [v for v in report.violations if v.rule_id == "RULE-TECH-001"]
    assert len(tech_violations) == 0


# ---------------------------------------------------------------------------
# 4. End-to-End Workflow Node Integration Tests
# ---------------------------------------------------------------------------


def test_investigate_node_establishes_truth_table_and_fact_claims():
    """In greenfield runs, investigate_node must populate truth table and record Claims."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh file://, MockAPI.io, chat tin nhắn",
                requirements=[
                    Requirement(id="REQ-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                    Requirement(id="REQ-002", text="MockAPI backend", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-owner", ttl=300)
            controller = WorkflowController(store, lease)

            def dummy_adapter(*args, **kwargs):
                return ModelResult(content={}, model_id="dummy", provider="fake")

            gateway = ModelGateway(config=GatewayConfig(), provider_adapter=dummy_adapter)
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute intake, intake_gate, snapshot, investigate
            # We transition state through snapshot to investigate
            controller.transition_phase(RunPhase.SNAPSHOT)
            controller.transition_phase(RunPhase.INVESTIGATE)

            # Test investigate_node directly from node logic
            inv_res = graph.nodes["investigate"].runnable.invoke(
                {"run_id": state.run.id, "round": 0, "events": []}
            )

            assert "tech_stack_truth_table" in inv_res
            truth_entries = inv_res["tech_stack_truth_table"].get("entries", [])
            assert len(truth_entries) >= 2

            # Verify claims recorded in repository
            latest_state = store.load(state.run.id)
            truth_claims = [c for c in latest_state.claims if "CLAIM-TRUTH" in c.id]
            assert len(truth_claims) >= 2
            assert any("file:// Protocol" in c.text for c in truth_claims)


def test_verify_node_detects_violation_and_records_blocking_issue():
    """When a proposal has physical violations, verify_node records BLOCKING issue and adds to review."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh file://, MockAPI.io, chat tin nhắn",
                requirements=[
                    Requirement(id="REQ-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                    Requirement(id="REQ-002", text="Chat tin nhắn", req_type=RequirementType.DELIV, acceptance="pass"),
                ],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-owner", ttl=300)
            controller = WorkflowController(store, lease)

            def dummy_adapter(*args, **kwargs):
                return ModelResult(content={}, model_id="dummy", provider="fake")

            gateway = ModelGateway(config=GatewayConfig(), provider_adapter=dummy_adapter)
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)

            # Simulate state after propose and review
            controller.transition_phase(RunPhase.SNAPSHOT)
            controller.transition_phase(RunPhase.INVESTIGATE)
            controller.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
            controller.transition_phase(RunPhase.PROPOSE)
            controller.transition_phase(RunPhase.REVIEW)

            flawed_proposal = ProposalOutput(
                approach="Dùng fetch('header.html') để tái sử dụng layout và reload trang khi gửi tin nhắn",
                requirement_coverage={"REQ-001": "fetch header"},
                claim_ids=[],
            )
            initial_review = ReviewOutput(
                summary="Initial review",
                issues=[],
            )

            verify_input = {
                "run_id": state.run.id,
                "round": 0,
                "events": [],
                "proposal": flawed_proposal.model_dump(mode="json"),
                "review": initial_review.model_dump(mode="json"),
            }

            verify_res = graph.nodes["verify"].runnable.invoke(verify_input)

            # Check that violations were found and recorded
            assert "verification_violations" in verify_res
            assert len(verify_res["verification_violations"]) > 0

            # Check that review dictionary received the new issues
            review_out = verify_res["review"]
            assert len(review_out["issues"]) > 0
            assert any("TECH-FILE-PROTOCOL" in iss["claim"] for iss in review_out["issues"])

            # Check that domain state recorded the BLOCKING issue
            latest_state = store.load(state.run.id)
            blocking_issues = [i for i in latest_state.issues if i.severity == IssueSeverity.BLOCKING]
            assert len(blocking_issues) > 0
            assert any("TECH-FILE-PROTOCOL" in bi.claim for bi in blocking_issues)
