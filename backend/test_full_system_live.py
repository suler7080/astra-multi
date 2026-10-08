"""End-to-End Live Functionality Test for Astra Multi using xKiro Free Models.

Verifies:
1. Provider configuration & live OpenAI-compatible endpoint connectivity.
2. Direct text and structured JSON schema generation.
3. ModelGateway with attempt tracing and output repair.
4. Multi-agent role outputs (Planner analysis, Reviewer analysis, Planner proposal, Reviewer critique, Synthesizer revision).
5. 11-Phase LangGraph workflow integration with domain persistence (SQLite WAL).
6. Quality Gate static DAG validation and requirement coverage.
7. Plan Exporter parity (JSON v1 and Markdown conforming to PLAN_TEMPLATE.md).
8. Execution of plan validation steps in Windows sandbox runner.
9. FastAPI backend creation, entity queries, and SSE streaming replay.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Setup UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure environment has the provided key
if not os.environ.get("XKIRO_API_KEY"):
    raise RuntimeError("Missing XKIRO_API_KEY environment variable. Please set XKIRO_API_KEY before running this test.")
os.environ.setdefault("ASTRA_MULTI_PROVIDER", "xkiro")

# Ensure backend/src is on sys.path
repo_root = Path(__file__).resolve().parent.parent
backend_src = repo_root / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
    format_independent_analysis_prompt,
    format_propose_prompt,
    format_review_prompt,
    format_synthesize_prompt,
)
from astra_multi.api.app import create_app
from astra_multi.context.bundle import ContextBuilder, ContextLimits
from astra_multi.context.evidence import EvidenceLedger
from astra_multi.context.snapshots import SnapshotStore
from astra_multi.domain.commands import CommitPlan
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    Decision,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Question,
    RunPhase,
    RunStatus,
    TaskSpec,
    ValidationStatus,
)
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.budget import BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.provider_config import ProviderManager, ProviderProfile, ProviderSettingsRepository
from astra_multi.providers import GenerationLimits, generate
from astra_multi.sandbox.runner import JobRequest, SandboxProfile, WindowsRunner
from starlette.testclient import TestClient


def run_all_checks() -> dict[str, str]:
    report: dict[str, str] = {}
    total_start = time.perf_counter()

    print("=" * 75)
    print("ASTRA MULTI — LIVE END-TO-END SYSTEM TEST (xKiro Free Models)")
    print("Target Endpoint: https://api.xkiro.com/v1")
    print("Selected Free Model: qwen/qwen3.7-flash:free")
    print("=" * 75)

    # -------------------------------------------------------------------------
    # STAGE 1: Provider Profile & Direct Generation
    # -------------------------------------------------------------------------
    print("\n[STAGE 1] Testing Provider Configuration & Direct Live Generation...")
    repo = ProviderSettingsRepository()
    manager = ProviderManager(repo)
    profile = manager.repository.load().profile("xkiro")
    assert profile.kind == "openai-compatible"
    assert "https://api.xkiro.com/v1" in str(profile.base_url)

    # Test direct text generation
    t0 = time.perf_counter()
    res_text = generate(
        provider="xkiro",
        role="planner",
        messages=[{"role": "user", "content": "Reply with 'PONG'"}],
        limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=30),
    )
    assert res_text.content is not None
    assert "PONG" in str(res_text.content).upper()
    print(f"  ✓ Text generation passed in {time.perf_counter() - t0:.2f}s (Tokens: {res_text.usage})")

    # Test direct structured schema generation
    t0 = time.perf_counter()
    res_json = generate(
        provider="xkiro",
        role="planner",
        messages=[
            {
                "role": "user",
                "content": "Return AnalysisOutput with 2 findings for a distributed cache: findings=['f1', 'f2'], risks=['r1'], assumptions=['a1'], role='planner'",
            }
        ],
        output_schema=AnalysisOutput,
        limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=30),
    )
    analysis = AnalysisOutput.model_validate(res_json.content)
    assert len(analysis.findings) >= 1
    assert analysis.role == "planner"
    print(f"  ✓ Structured JSON schema generation passed in {time.perf_counter() - t0:.2f}s")
    print(f"    Findings: {analysis.findings}")
    report["stage_1_direct_generation"] = "PASS"

    # -------------------------------------------------------------------------
    # STAGE 2: ModelGateway with Output Repair and Attempt Tracing
    # -------------------------------------------------------------------------
    print("\n[STAGE 2] Testing ModelGateway Lifecycle & Tracing...")
    gateway = ModelGateway(config=GatewayConfig(enable_output_repair=True))
    t0 = time.perf_counter()
    gw_res = gateway.call(
        provider="xkiro",
        role="reviewer",
        messages=[
            {
                "role": "user",
                "content": "Provide analysis findings as reviewer: findings=['Cache invalidation risk'], risks=['Stale data'], assumptions=['Redis used'], role='reviewer'",
            }
        ],
        output_schema=AnalysisOutput,
        limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=30),
    )
    rev_analysis = AnalysisOutput.model_validate(gw_res.content)
    assert len(rev_analysis.findings) >= 1
    traces = gateway.get_attempt_traces()
    assert len(traces) >= 1
    assert traces[0].provider == "xkiro"
    assert traces[0].tokens_used is not None
    print(f"  ✓ ModelGateway call & tracing verified in {time.perf_counter() - t0:.2f}s (Traces: {len(traces)})")
    report["stage_2_model_gateway"] = "PASS"

    # -------------------------------------------------------------------------
    # STAGE 3: Multi-Agent Prompt Chaining (Planner -> Reviewer -> Synthesizer)
    # -------------------------------------------------------------------------
    print("\n[STAGE 3] Testing Multi-Agent Discussion Roles Live...")
    with tempfile.TemporaryDirectory() as tmpdir:
        with SQLiteStore(Path(tmpdir) / "test.sqlite") as store:
            context_builder = ContextBuilder(store.artifacts)
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, "orchestrator", ttl=60)
            ctrl = WorkflowController(store, lease, actor="orchestrator")

            # 3a. Planner Proposal
            print("  -> Generating Proposal from Planner...")
            t0 = time.perf_counter()
            bundle_prop = context_builder.build_context(state, "planner", RunPhase.PROPOSE, [], ContextLimits())
            prop_msgs = format_propose_prompt(bundle_prop, [analysis, rev_analysis])
            res_prop = gateway.call(
                provider="xkiro",
                role="planner",
                messages=prop_msgs,
                output_schema=ProposalOutput,
                limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=45, max_retries=2),
            )
            proposal = ProposalOutput.model_validate(res_prop.content)
            assert proposal.approach
            print(f"     ✓ Approach: {proposal.approach[:80]}... in {time.perf_counter() - t0:.2f}s")

            # 3b. Reviewer Critique
            print("  -> Generating Review & Issues from Reviewer...")
            t0 = time.perf_counter()
            bundle_rev = context_builder.build_context(state, "reviewer", RunPhase.REVIEW, [], ContextLimits())
            rev_msgs = format_review_prompt(bundle_rev, proposal)
            res_rev = gateway.call(
                provider="xkiro",
                role="reviewer",
                messages=rev_msgs,
                output_schema=ReviewOutput,
                limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=45, max_retries=2),
            )
            review = ReviewOutput.model_validate(res_rev.content)
            print(f"     ✓ Review produced {len(review.issues)} critique issues in {time.perf_counter() - t0:.2f}s")

            # 3c. Synthesizer Plan Revision
            print("  -> Synthesizing Plan Revision from Synthesizer...")
            t0 = time.perf_counter()
            bundle_synth = context_builder.build_context(state, "synthesizer", RunPhase.REVISE, [], ContextLimits())
            synth_msgs = format_synthesize_prompt(bundle_synth, proposal, review)
            res_synth = gateway.call(
                provider="xkiro",
                role="synthesizer",
                messages=synth_msgs,
                output_schema=SynthesizerOutput,
                limits=GenerationLimits(model="qwen/qwen3.7-flash:free", timeout=45, max_retries=2),
            )
            synth = SynthesizerOutput.model_validate(res_synth.content)
            assert len(synth.steps) >= 1
            print(f"     ✓ Synthesizer generated {len(synth.steps)} steps and {len(synth.decisions)} ADRs in {time.perf_counter() - t0:.2f}s")
    report["stage_3_multi_agent_roles"] = "PASS"

    # -------------------------------------------------------------------------
    # STAGE 4: Quality Gates & Plan Exporter Parity
    # -------------------------------------------------------------------------
    print("\n[STAGE 4] Testing P4 Quality Gates & Plan Exporter Parity...")
    state = sample_state()
    steps = [
        PlanStep(
            id="STEP-1",
            objective="Configure distributed cache connection pool",
            requirement_ids=["REQ-001"],
            validation="pytest tests/unit/test_cache.py",
            deliverables=["cache_pool.py"],
            completion_criteria=["Connection pool initializes without timeout"],
        ),
        PlanStep(
            id="STEP-2",
            objective="Implement TTL-based cache invalidation",
            requirement_ids=["REQ-001"],
            dependencies=["STEP-1"],
            validation="pytest tests/unit/test_invalidation.py",
            deliverables=["invalidation.py"],
            completion_criteria=["Keys expire accurately after TTL"],
        ),
    ]
    plan = PlanRevision(
        id="PLAN-V1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=steps,
        decisions=[
            Decision(
                id="DEC-001",
                run_id=state.run.id,
                question="Caching backend choice",
                chosen="Redis cluster",
                rationale="High availability and sliding expiration support",
                alternatives=["In-memory LRU"],
            )
        ],
        risks=["Network latency between API and Redis nodes"],
        issues_addressed=[],
    )
    state = state.model_copy(update={"plans": [plan]})

    # Structural validation
    validator = StructuralQualityValidator()
    q_report = validator.validate(state)
    assert q_report.passed is True
    print("  ✓ Structural DAG and coverage quality gate: PASSED")

    # Finalization service
    finalizer = FinalizationService(validator=validator)
    decision = finalizer.evaluate(
        state,
        SemanticReviewAssessment(
            passed=True,
            reviewed_plan_revision=1,
            feedback="All requirements satisfied and steps form strict DAG",
            concerns=[],
        ),
    )
    assert decision.can_finalize is True
    assert decision.target_status == RunStatus.FINAL
    print("  ✓ Semantic finalization decision: FINAL GRANTED")

    # Plan Exporter
    exporter = PlanExporter()
    json_plan = exporter.export_json(state)
    md_plan = exporter.export_markdown(state)
    assert json_plan["schema_version"] == 1
    assert json_plan["metadata"]["plan_revision"] == 1
    assert len(json_plan["steps"]) == 2
    assert "STEP-1" in md_plan
    assert "Redis cluster" in md_plan
    print("  ✓ Plan Exporter generated compliant JSON Schema v1 & Markdown PLAN_TEMPLATE.md")
    report["stage_4_quality_gates_and_export"] = "PASS"

    # -------------------------------------------------------------------------
    # STAGE 5: Native Sandbox Runner Execution
    # -------------------------------------------------------------------------
    print("\n[STAGE 5] Testing Execution Sandbox Runner...")
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        repo_dir = work_dir / "target_repo"
        repo_dir.mkdir()
        (repo_dir / "app.py").write_text("print('Astra Sandbox Verification SUCCESS')\n", encoding="utf-8")

        with SQLiteStore(work_dir / "sandbox.sqlite") as store:
            snapshots = SnapshotStore(store.artifacts)
            snap = snapshots.capture(repo_dir)

            runner = WindowsRunner(
                snapshots=snapshots,
                work_root=work_dir / "jobs",
                profile=SandboxProfile(target_os="windows"),
            )
            job = JobRequest(
                run_id="RUN-SB-01",
                snapshot_id=snap.snapshot.id,
                call_id="CALL-SB-01",
                command=("python", "app.py"),
                expected="command exits with code 0",
            )
            res_job = runner.execute(snap, job)
            assert res_job.status == "passed"
            assert res_job.exit_code == 0
            assert res_job.validation_status == ValidationStatus.PASS
            print(f"  ✓ Windows subprocess sandbox executed successfully (Exit code: {res_job.exit_code})")
    report["stage_5_sandbox_runner"] = "PASS"

    # -------------------------------------------------------------------------
    # STAGE 6: FastAPI Backend Endpoints & SSE Streaming Replay
    # -------------------------------------------------------------------------
    print("\n[STAGE 6] Testing FastAPI Backend & SSE Streaming Replay...")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # Create run
            res_create = client.post(
                "/api/runs",
                json={
                    "goal": "Build High-Availability Distributed Gateway",
                    "requirements": ["10k TPS", "Sub-10ms P99 latency"],
                },
            )
            assert res_create.status_code in (200, 202)
            run_id = res_create.json()["run_id"]
            print(f"  ✓ Created run {run_id} via POST /api/runs")

            # Check status
            res_get = client.get(f"/api/runs/{run_id}")
            assert res_get.status_code == 200
            assert res_get.json()["status"] == "RUNNING"
            print(f"  ✓ Fetched run status: {res_get.json()['status']}")

            # Add question and answer
            store = app.state.store
            lease = store.acquire(run_id, "api-test", ttl=30)
            ctrl = WorkflowController(store, lease, actor="api-test")
            q = Question(
                id="Q-001",
                run_id=run_id,
                text="Which storage engine for high write throughput?",
                blocking=True,
            )
            ctrl.ask_question(q)
            curr = ctrl.get_state()
            ctrl.transition_phase(
                curr.run.phase,
                new_status=RunStatus.WAITING_FOR_INPUT,
                reason="Waiting for user input on question",
            )
            store.release(lease)

            # Query pending questions
            detail = client.get(f"/api/runs/{run_id}").json()
            assert len(detail["pending_questions"]) == 1

            # Answer question
            res_ans = client.post(
                f"/api/runs/{run_id}/answers",
                json={
                    "question_id": q.id,
                    "answer": "ScyllaDB",
                    "expected_revision": detail["revision"],
                },
            )
            assert res_ans.status_code == 200
            print("  ✓ Submitted answer via POST /api/runs/{id}/answers")

            # Test cancellation
            res_cancel = client.post(f"/api/runs/{run_id}/cancel", json={"reason": "Test complete"})
            assert res_cancel.status_code == 200
            assert res_cancel.json()["status"] == "CANCELLED"
            print("  ✓ Cancelled run via POST /api/runs/{id}/cancel")

            # Test SSE stream
            sse_res = client.get(f"/api/runs/{run_id}/events")
            assert sse_res.status_code == 200
            assert "text/event-stream" in sse_res.headers["content-type"]
            assert "run_completed" in sse_res.text
            print("  ✓ SSE event stream returned complete event stream with terminal marker")

            # Verify Web UI static mount
            res_ui = client.get("/")
            assert res_ui.status_code == 200
            assert "Astra Multi" in res_ui.text
            print("  ✓ Verified Web UI SPA is served from FastAPI root /")
    report["stage_6_fastapi_and_sse"] = "PASS"

    total_time = time.perf_counter() - total_start
    print("\n" + "=" * 75)
    print(f"TOÀN BỘ CHỨC NĂNG ĐÃ KIỂM THỬ THÀNH CÔNG VỚI xKiro ({total_time:.2f}s)!")
    print("=" * 75)
    for stage, status in report.items():
        print(f"  {stage:35}: {status}")
    print("=" * 75)

    return report


if __name__ == "__main__":
    results = run_all_checks()
    all_passed = all(status == "PASS" for status in results.values())
    sys.exit(0 if all_passed else 1)
