"""Unit tests for Executable Sandbox Constraint Verification (src/astra_multi/sandbox/)."""

from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from astra_multi.agents.roles import ProposalOutput, ReviewOutput
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    Evidence,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    RequirementType,
    RunPhase,
    StepPhaseType,
    TaskSpec,
    ToolCall,
    ValidationResult,
    ValidationStatus,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.verifier import PlanSandboxVerifier, SandboxVerificationOutcome


def make_step(
    step_id: str,
    req_ids: list[str],
    deliverable: str,
    validation: str = "Test verification method",
    dependencies: list[str] | None = None,
    phase_type: StepPhaseType = StepPhaseType.CORE_MODULE,
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


def test_plan_sandbox_verifier_script_generation():
    """Verify that PlanSandboxVerifier generates executable Python code embedding plan items and rules."""
    task = TaskSpec(
        id="TASK-001",
        revision=1,
        goal="Xây dựng web tĩnh mở trực tiếp file://",
        requirements=[
            Requirement(
                id="REQ-TECH-001",
                text="Mở trực tiếp file:// không dùng web server",
                req_type=RequirementType.TECH,
                acceptance="Double click index.html",
            )
        ],
    )
    step = make_step("STEP-1", ["REQ-TECH-001"], "Dùng thẻ script defer layout.js")
    base_state = sample_state(repo=False)
    plan = PlanRevision(
        id="PLAN-1",
        run_id=base_state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
        decisions=[],
        risks=[],
    )

    verifier = PlanSandboxVerifier()
    script = verifier.generate_verification_script(task, plan)

    assert "ASTRA MULTI-AGENT ARCHITECTURE CONSTRAINT SANDBOX VERIFIER" in script
    assert "STEP-1:deliverable[0]" in script
    assert "TECH-FILE-001" in script
    assert "module" in script and "TECH-FILE-001" in script


def test_plan_sandbox_verifier_clean_plan_execution():
    """A compliant plan without forbidden patterns passes sandbox execution with exit code 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh mở file:// trực tiếp, MockAPI backend, chat tin nhắn",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                    Requirement(id="REQ-TECH-002", text="MockAPI backend", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step1 = make_step(
                "STEP-1", ["REQ-TECH-001"],
                deliverable="Nhúng layout.js qua <script defer src='js/layout.js'> tiêm header/footer vào DOM qua template literal",
            )
            step2 = make_step(
                "STEP-2", ["REQ-TECH-002"],
                deliverable="Chat module gửi POST bất đồng bộ tới MockAPI và cập nhật appendChild vào DOM",
                dependencies=["STEP-1"],
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step1, step2],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            store.commit(state.run.id, None, None) if False else None
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            assert outcome.passed is True
            assert outcome.exit_code == 0
            assert len(outcome.violations) == 0
            assert "PASSED" in outcome.output_log

            assert tool_call is not None
            assert tool_call.exit_code == 0

            assert evidence is not None
            assert evidence.status == ValidationStatus.PASS
            assert evidence.tool_call_id == tool_call.id

            assert validation is not None
            assert validation.status == ValidationStatus.PASS
            assert validation.exit_code == 0

            assert len(issues) == 0

            # Verify in repository
            latest_state = store.load(state.run.id)
            assert any(t.id == tool_call.id for t in latest_state.tool_calls)
            assert any(e.id == evidence.id for e in latest_state.evidence)
            assert any(v.id == validation.id for v in latest_state.validations)


def test_plan_sandbox_verifier_flawed_plan_file_cors_module():
    """When plan proposes type='module' under file://, sandbox execution fails and records failed Evidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh mở file:// trực tiếp không cần web server",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step_flawed = make_step(
                "STEP-1", ["REQ-TECH-001"],
                deliverable='Nhúng script bằng <script type="module" src="app.js"> và dùng import { api } from "./api.js"',
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step_flawed],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            # Execution failed
            assert outcome.passed is False
            assert outcome.exit_code == 1
            assert len(outcome.violations) > 0
            assert any("TECH-FILE-001" in v or "type=\"module\"" in v for v in outcome.violations)

            # ToolCall recorded with non-zero exit code
            assert tool_call is not None
            assert tool_call.exit_code == 1

            # Evidence recorded with ValidationStatus.FAIL
            assert evidence is not None
            assert evidence.status == ValidationStatus.FAIL
            assert evidence.tool_call_id == tool_call.id
            assert evidence.source_type == "tool"

            # ValidationResult recorded with ValidationStatus.FAIL
            assert validation is not None
            assert validation.status == ValidationStatus.FAIL
            assert validation.exit_code == 1
            assert validation.tool_call_id == tool_call.id
            assert validation.evidence_ids == [evidence.id]

            # BLOCKING issue opened referencing evidence.id
            assert len(issues) > 0
            for iss in issues:
                assert iss.severity == IssueSeverity.BLOCKING
                assert iss.status == IssueStatus.OPEN
                assert evidence.id in iss.evidence_ids

            # State invariants verified in repository
            latest_state = store.load(state.run.id)
            assert any(e.id == evidence.id and e.status == ValidationStatus.FAIL for e in latest_state.evidence)
            assert any(v.id == validation.id and v.status == ValidationStatus.FAIL for v in latest_state.validations)
            assert any(i.severity == IssueSeverity.BLOCKING and evidence.id in i.evidence_ids for i in latest_state.issues)


def test_plan_sandbox_verifier_flawed_plan_fetch_header():
    """When plan proposes fetch('./header.html') under file://, sandbox execution detects CORS violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh mở file:// trực tiếp",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step_flawed = make_step(
                "STEP-1", ["REQ-TECH-001"],
                deliverable="Tái sử dụng layout bằng hàm fetch('./header.html') và tiêm vào phần tử #header-container",
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step_flawed],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            assert outcome.passed is False
            assert evidence.status == ValidationStatus.FAIL
            assert any("TECH-FILE-003" in v or "fetch" in v for v in outcome.violations)
            assert any(evidence.id in iss.evidence_ids for iss in issues)


def test_plan_sandbox_verifier_flawed_plan_location_reload():
    """When plan uses location.reload() for chat UI, sandbox execution flags UX constraint violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web chat tin nhắn thời gian thực",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="Chat tin nhắn", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step_flawed = make_step(
                "STEP-1", ["REQ-TECH-001"],
                deliverable="Sau khi người dùng gửi tin nhắn, gọi location.reload() để tải lại danh sách tin nhắn mới",
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step_flawed],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            assert outcome.passed is False
            assert evidence.status == ValidationStatus.FAIL
            assert any("TECH-CHAT-001" in v or "location.reload" in v for v in outcome.violations)


def test_plan_sandbox_verifier_flawed_plan_mockapi_jwt():
    """When plan claims MockAPI generates JWT tokens, sandbox flags backend limitation violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tuyển dụng kết nối MockAPI.io REST API",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="MockAPI.io backend", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step_flawed = make_step(
                "STEP-1", ["REQ-TECH-001"],
                deliverable="Thiết kế backend MockAPI sinh JWT token gửi về client khi người dùng đăng nhập",
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step_flawed],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            assert outcome.passed is False
            assert evidence.status == ValidationStatus.FAIL
            assert any("TECH-MOCKAPI-001" in v or "MockAPI sinh JWT" in v for v in outcome.violations)


def test_plan_sandbox_verifier_negation_not_flagged():
    """Explicitly rejecting or avoiding a prohibited pattern is not flagged as a violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir) / "artifacts")
        db_path = Path(tmpdir) / "test.db"

        with SQLiteStore(db_path) as store:
            base_state = sample_state(repo=False)
            task = TaskSpec(
                id="TASK-001",
                revision=1,
                goal="Web tĩnh mở file:// trực tiếp, MockAPI backend, chat tin nhắn",
                requirements=[
                    Requirement(id="REQ-TECH-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                    Requirement(id="REQ-TECH-002", text="Chat tin nhắn", req_type=RequirementType.TECH, acceptance="pass"),
                ],
            )
            step = make_step(
                "STEP-1", ["REQ-TECH-001", "REQ-TECH-002"],
                deliverable="Tuyệt đối không dùng type='module' và tránh location.reload(); dùng hàm render trực tiếp vào DOM",
            )
            plan = PlanRevision(
                id="PLAN-1",
                run_id=base_state.run.id,
                revision=1,
                based_on_revision=0,
                requirements_revision=1,
                snapshot_id=None,
                steps=[step],
                decisions=[],
                risks=[],
            )
            state = base_state.model_copy(update={"task": task, "tasks": [task], "plan": plan, "plans": [plan]})
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="verifier-test", ttl=300)
            controller = WorkflowController(store, lease)
            controller.commit_plan_revision(plan)

            verifier = PlanSandboxVerifier(artifacts=art_store)
            outcome, tool_call, evidence, validation, issues = verifier.verify(
                task=task,
                plan=plan,
                controller=controller,
            )

            assert outcome.passed is True
            assert outcome.exit_code == 0
            assert len(outcome.violations) == 0


def test_verify_node_end_to_end_records_sandbox_evidence_and_failure():
    """Integration test verifying that verify_node runs PlanSandboxVerifier and records failed Evidence in DB."""
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
                    Requirement(id="REQ-TECH-001", text="Mở file:// trực tiếp", req_type=RequirementType.TECH, acceptance="pass"),
                    Requirement(id="REQ-TECH-002", text="Chat tin nhắn", req_type=RequirementType.DELIV, acceptance="pass"),
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

            # Move state to REVIEW
            controller.transition_phase(RunPhase.SNAPSHOT)
            controller.transition_phase(RunPhase.INVESTIGATE)
            controller.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
            controller.transition_phase(RunPhase.PROPOSE)
            controller.transition_phase(RunPhase.REVIEW)

            flawed_proposal = ProposalOutput(
                approach="Dùng fetch('header.html') để tái sử dụng layout và reload trang khi gửi tin nhắn",
                requirement_coverage={"REQ-TECH-001": "fetch header"},
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

            # verify_node should execute sandbox and record results
            assert "sandbox_passed" in verify_res
            assert verify_res["sandbox_passed"] is False
            assert len(verify_res["sandbox_violations"]) > 0

            # Verify that state in repository has ToolCall, failed Evidence, and failed Validation
            latest_state = store.load(state.run.id)
            assert len(latest_state.tool_calls) > 0
            failed_evidence = [e for e in latest_state.evidence if e.status == ValidationStatus.FAIL]
            assert len(failed_evidence) > 0

            failed_validations = [v for v in latest_state.validations if v.status == ValidationStatus.FAIL]
            assert len(failed_validations) > 0

            # Verify that blocking issues reference the failed evidence
            blocking_with_evidence = [
                i for i in latest_state.issues
                if i.severity == IssueSeverity.BLOCKING and any(fe.id in i.evidence_ids for fe in failed_evidence)
            ]
            assert len(blocking_with_evidence) > 0
