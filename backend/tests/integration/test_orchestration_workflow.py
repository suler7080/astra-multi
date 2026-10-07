"""Integration tests for the LangGraph multi-agent discussion workflow (P3.3)."""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    IssueResolutionReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
)
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import Issue, IssueSeverity, IssueStatus, PlanRevision, PlanStep, Requirement, RunPhase, RunStatus
from astra_multi.exports.finalization import FinalizationService, SemanticReviewAssessment
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.schemas import ModelResult


def fake_model_adapter(
    provider: str,
    role: str,
    messages: list[dict[str, str]],
    output_schema: Any = None,
    **kwargs: Any,
) -> ModelResult:
    """Deterministic adapter for workflow testing."""
    if output_schema == AnalysisOutput:
        content = AnalysisOutput(
            role="planner" if role == "planner" else "reviewer",
            findings=[f"{role} found service architecture is valid"],
            risks=["Potential lock contention"],
            assumptions=["PostgreSQL database"],
            marker=f"{role}-marker",
        )
    elif output_schema == ProposalOutput:
        content = ProposalOutput(
            approach="Implement robust healthcheck endpoint",
            alternatives=["Ping endpoint"],
            tradeoffs=["Low latency vs full dependency probe"],
            requirement_coverage={"REQ-001": "Direct HTTP handler returns 200"},
            claim_ids=[],
        )
    elif output_schema == ReviewOutput:
        content = ReviewOutput(
            summary="Review completed with warning",
            reviewed_evidence_ids=[],
            issues=[
                IssueReport(
                    claim="No timeout specified on health endpoint probe",
                    impact="Possible thread starvation",
                    severity=IssueSeverity.WARNING,
                    verification_request="Verify health endpoint response with network delay simulated",
                    suggested_resolution="Add 2-second timeout",
                    requirement_ids=["REQ-001"],
                )
            ],
        )
    elif output_schema == SynthesizerOutput:
        content = SynthesizerOutput(
            steps=[
                StepDraft(
                    objective="Implement /health HTTP route",
                    requirement_ids=["REQ-001"],
                    dependencies=[],
                    targets=["app/routes.py"],
                    validation="pytest tests/test_health.py passes",
                    deliverables=["health route implementation"],
                    completion_criteria=["HTTP 200 returned"],
                    evidence_ids=[],
                )
            ],
            decisions=[
                DecisionDraft(
                    question="Which route decorator to use?",
                    chosen="@app.get('/health')",
                    rationale="Standard FastAPI pattern",
                    alternatives=["@app.route"],
                    evidence_ids=[],
                    related_issue_ids=[],
                )
            ],
            risks=["High load on health route"],
            issues_addressed=[],
            rationale="FastAPI route provides clean async handling",
        )
    else:
        content = "ok"

    return ModelResult(
        content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
        model_id=f"fake-{role}",
        provider="fake",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        cost_actual_usd=0.001,
    )


def test_full_workflow_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=fake_model_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute run
            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            assert final_output["gate_passed"] is True
            assert final_output["round"] >= 1

            # Verify persisted domain state
            final_domain_state = store.load(state.run.id)
            assert final_domain_state.run.phase == RunPhase.EXPORT
            assert final_domain_state.run.status == RunStatus.PARTIAL  # Reserved: FINAL is for P4
            assert len(final_domain_state.plans) >= 1
            assert len(final_domain_state.proposals) >= 1
            assert len(final_domain_state.issues) >= 1
            assert len(final_domain_state.decisions) >= 1
            assert len(final_domain_state.model_calls) >= 4  # planner analysis, reviewer analysis, propose, review, synth


def test_workflow_sanitizes_unvalidated_llm_references():
    """Verifies that LLMs outputting unknown claim IDs or requirement IDs do not fail RunState validation."""
    def hallucinating_model_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role="planner" if role == "planner" else "reviewer",
                findings=["Finding 1"],
                risks=["Risk 1"],
                assumptions=["Assumption 1"],
            )
        elif output_schema == ProposalOutput:
            # LLM mistakenly puts requirement IDs in claim_ids and unknown requirement in coverage
            content = ProposalOutput(
                approach="Caching service approach",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Covered", "UNKNOWN_REQ": "Covered"},
                claim_ids=["REQ-001", "REQ-002", "CLAIM-DOES-NOT-EXIST"],
            )
        elif output_schema == ReviewOutput:
            # LLM puts unknown requirement and evidence IDs
            content = ReviewOutput(
                summary="Review completed",
                issues=[
                    IssueReport(
                        claim="Issue without evidence or explicit verif req",
                        impact="High impact",
                        severity=IssueSeverity.WARNING,
                        verification_request=None,
                        suggested_resolution="Fix it",
                        requirement_ids=["UNKNOWN_REQ", "REQ-001"],
                        evidence_ids=["UNKNOWN_EVIDENCE"],
                    )
                ],
            )
        elif output_schema == SynthesizerOutput:
            # LLM puts unknown requirement and evidence IDs and cyclic/unknown dependencies
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Step 1",
                        requirement_ids=["UNKNOWN_REQ"],
                        dependencies=["STEP-999"],
                        targets=[],
                        validation="test",
                        deliverables=["Artifact"],
                        completion_criteria=["Criteria"],
                        evidence_ids=["UNKNOWN_EVIDENCE"],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question="Decision question",
                        chosen="Option A",
                        rationale="Rationale",
                        alternatives=[],
                        evidence_ids=["UNKNOWN_EVIDENCE"],
                        related_issue_ids=["UNKNOWN_ISSUE"],
                    )
                ],
                risks=[],
                issues_addressed=["UNKNOWN_ISSUE"],
                rationale="Rationale",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=hallucinating_model_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }
            # This must complete successfully without crashing on unknown references!
            final_output = app.invoke(initial_state)
            assert final_output["gate_passed"] is True

            final_domain_state = store.load(state.run.id)
            assert len(final_domain_state.proposals) >= 1
            # proposal claim_ids must be sanitized to valid claims (empty here)
            assert final_domain_state.proposals[0].claim_ids == []
            # coverage must not have UNKNOWN_REQ
            assert "UNKNOWN_REQ" not in final_domain_state.proposals[0].requirement_coverage


def test_workflow_multi_round_decision_id_uniqueness():
    """Verifies that multi-round discussions produce unique decision IDs without operation key conflicts."""
    round_calls: dict[str, int] = {"synth": 0}

    def multi_round_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role="planner" if role == "planner" else "reviewer",
                findings=["Valid base architecture"],
                risks=[],
                assumptions=[],
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Multi-round architecture test",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Full coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            content = ReviewOutput(
                summary="Review completed",
                reviewed_evidence_ids=[],
                issues=[],
            )
        elif output_schema == SynthesizerOutput:
            round_calls["synth"] += 1
            call_num = round_calls["synth"]
            # In round 1 (call_num == 1), leave REQ-002 uncovered to force loop to round 2
            req_ids = ["REQ-001"] if call_num == 1 else ["REQ-001", "REQ-002"]
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective=f"Step in round {call_num}",
                        requirement_ids=req_ids,
                        dependencies=[],
                        targets=["module.py"],
                        validation="pytest",
                        deliverables=["code"],
                        completion_criteria=["tests pass"],
                        evidence_ids=[],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question=f"Decision Q for round {call_num}?",
                        chosen=f"Option {call_num}",
                        rationale=f"Rationale {call_num}",
                        alternatives=[],
                        evidence_ids=[],
                        related_issue_ids=[],
                    )
                ],
                risks=[],
                issues_addressed=[],
                rationale="Multi-round synthesis",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_multiround.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            state.task.requirements.append(
                Requirement(
                    id="REQ-002",
                    text="Secondary endpoint requirement",
                    acceptance="GET /metrics returns 200",
                )
            )
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=multi_round_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }
            # This must complete both rounds without OperationConflict!
            final_output = app.invoke(initial_state)
            assert final_output["gate_passed"] is True
            assert round_calls["synth"] == 2

            final_domain_state = store.load(state.run.id)
            # Verify both decisions exist and have distinct IDs
            dec_ids = [d.id for d in final_domain_state.decisions]
            assert len(dec_ids) == 2
            assert len(set(dec_ids)) == 2
            assert "DEC-1" in dec_ids
            assert "DEC-2" in dec_ids


def test_f003_no_spoofing_when_llm_omits_coverage():
    """F-003: If LLM omits requirement coverage, state must retain missing data and Gate must reject."""
    def missing_coverage_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role="planner" if role == "planner" else "reviewer",
                findings=["Valid base architecture"],
                risks=[],
                assumptions=[],
            )
        elif output_schema == ProposalOutput:
            # LLM completely omits requirement_coverage
            content = ProposalOutput(
                approach="Custom approach with no explicit requirement coverage map",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            content = ReviewOutput(
                summary="Review completed",
                reviewed_evidence_ids=[],
                issues=[],
            )
        elif output_schema == SynthesizerOutput:
            # Synthesizer covers only REQ-001, leaving REQ-002 uncovered
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Step covering REQ-001 only",
                        requirement_ids=["REQ-001"],
                        dependencies=[],
                        targets=["module.py"],
                        validation="pytest",
                        deliverables=["code"],
                        completion_criteria=["tests pass"],
                        evidence_ids=[],
                    )
                ],
                decisions=[],
                risks=[],
                issues_addressed=[],
                rationale="Partial synthesis missing REQ-002",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_f003.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            state.task.requirements.append(
                Requirement(
                    id="REQ-002",
                    text="Secondary endpoint requirement",
                    acceptance="GET /metrics returns 200",
                )
            )
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=missing_coverage_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 1,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            # Gate must REJECT because REQ-002 is uncovered
            assert final_output["gate_passed"] is False
            assert "Missing requirement coverage" in final_output["stop_reason"]

            final_domain_state = store.load(state.run.id)
            # Proposal requirement_coverage must be empty - NOT spoofed with approach[:100]!
            assert len(final_domain_state.proposals) >= 1
            assert final_domain_state.proposals[0].requirement_coverage == {}


def test_f008_quality_gate_detects_dag_cycle():
    """F-008: quality_gate_node must call StructuralQualityValidator and reject plans with DAG cycles."""
    state = sample_state(repo=False)
    step1 = PlanStep(
        id="STEP-1",
        objective="Step 1",
        requirement_ids=["REQ-001"],
        dependencies=["STEP-2"],
        targets=["app.py"],
        validation="pytest",
        deliverables=["code"],
        completion_criteria=["tests pass"],
    )
    step2 = PlanStep(
        id="STEP-2",
        objective="Step 2",
        requirement_ids=["REQ-001"],
        dependencies=["STEP-1"],
        targets=["app.py"],
        validation="pytest",
        deliverables=["code"],
        completion_criteria=["tests pass"],
    )
    cyclic_plan = PlanRevision.model_construct(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2],
        decisions=[],
        risks=[],
        issues_addressed=[],
    )
    state = state.model_copy(update={"plans": [cyclic_plan]})

    ctrl = MagicMock()
    ctrl.get_state.return_value = state
    wf_ctx = MagicMock(controller=ctrl, stagnation_detector=StagnationDetector())
    graph = create_workflow_graph(wf_ctx)

    result = graph.nodes["gate"].runnable.invoke({"round": 0, "max_rounds": 2})

    assert result["gate_passed"] is False
    assert "Dependency cycle" in result["stop_reason"] or "RULE-DAG-002" in result["stop_reason"]


def test_f006_review_node_ignores_deleted_requirements():
    """F-006: review_node must use curr_state.task.requirements so deleted requirements are omitted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_f006.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            old_task = state.task.model_copy(
                update={
                    "requirements": [
                        Requirement(id="REQ-DELETED", text="Obsolete requirement", acceptance="none"),
                        Requirement(id="REQ-001", text="Active requirement", acceptance="pass"),
                    ]
                }
            )
            store.create(old_task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, "worker", 60)
            ctrl = WorkflowController(store, lease)

            # Revise task to remove REQ-DELETED
            new_task = old_task.model_copy(
                update={
                    "revision": 2,
                    "requirements": [Requirement(id="REQ-001", text="Active requirement", acceptance="pass")],
                }
            )
            ctrl.revise_task(new_task, reason="Removed REQ-DELETED")

            def adapter(
                provider: str,
                role: str,
                messages: list[dict[str, str]],
                output_schema: Any = None,
                **kwargs: Any,
            ) -> ModelResult:
                if output_schema == AnalysisOutput:
                    content = AnalysisOutput(role="planner", findings=["ok"])
                elif output_schema == ProposalOutput:
                    content = ProposalOutput(approach="app", requirement_coverage={"REQ-001": "cov"})
                elif output_schema == ReviewOutput:
                    content = ReviewOutput(
                        summary="Review mentioning both old and active requirements",
                        issues=[
                            IssueReport(
                                claim="Issue referencing deleted req",
                                impact="impact",
                                severity=IssueSeverity.WARNING,
                                requirement_ids=["REQ-DELETED", "REQ-001"],
                                suggested_resolution="fix",
                            )
                        ],
                    )
                elif output_schema == SynthesizerOutput:
                    content = SynthesizerOutput(
                        steps=[
                            StepDraft(
                                objective="o",
                                requirement_ids=["REQ-001"],
                                validation="v",
                                deliverables=["d"],
                                completion_criteria=["c"],
                            )
                        ],
                        decisions=[],
                        risks=[],
                        issues_addressed=[],
                        rationale="r",
                    )
                else:
                    content = "ok"
                return ModelResult(
                    content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
                    model_id="m",
                    provider="p",
                    usage={},
                    cost_actual_usd=0,
                )

            ctx = WorkflowContext(
                controller=ctrl,
                gateway=ModelGateway(GatewayConfig(enable_output_repair=False), provider_adapter=adapter),
                context_builder=ContextBuilder(art_store),
            )
            g = create_workflow_graph(ctx).compile()
            g.invoke({"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []})

            final_state = store.load(state.run.id)
            assert len(final_state.issues) >= 1
            # REQ-DELETED was removed in current task revision, so it must not be in issue requirement_ids
            assert "REQ-DELETED" not in final_state.issues[0].requirement_ids
            assert final_state.issues[0].requirement_ids == ["REQ-001"]


def test_f001_multi_round_calls_propose_each_round():
    """F-001: should_loop_or_export must return 'propose', calling propose_node in every loop round."""
    round_calls: dict[str, int] = {"propose": 0, "synth": 0}

    def multi_round_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role="planner" if role == "planner" else "reviewer",
                findings=["Base architecture"],
                risks=[],
                assumptions=[],
            )
        elif output_schema == ProposalOutput:
            round_calls["propose"] += 1
            call_num = round_calls["propose"]
            content = ProposalOutput(
                approach=f"Approach in round {call_num}",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Covered"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            content = ReviewOutput(
                summary="Review completed",
                reviewed_evidence_ids=[],
                issues=[],
            )
        elif output_schema == SynthesizerOutput:
            round_calls["synth"] += 1
            call_num = round_calls["synth"]
            # Round 1 leaves REQ-002 uncovered to force loop; round 2 covers both
            req_ids = ["REQ-001"] if call_num == 1 else ["REQ-001", "REQ-002"]
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective=f"Step in round {call_num}",
                        requirement_ids=req_ids,
                        dependencies=[],
                        targets=["module.py"],
                        validation="pytest",
                        deliverables=["code"],
                        completion_criteria=["tests pass"],
                        evidence_ids=[],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question=f"Q for round {call_num}",
                        chosen=f"Option {call_num}",
                        rationale="r",
                        alternatives=[],
                        evidence_ids=[],
                        related_issue_ids=[],
                    )
                ],
                risks=[],
                issues_addressed=[],
                rationale="Synthesis",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_f001.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            state.task.requirements.append(
                Requirement(
                    id="REQ-002",
                    text="Second requirement",
                    acceptance="pass",
                )
            )
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=multi_round_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            assert final_output["gate_passed"] is True
            assert round_calls["synth"] == 2
            # F-001 assertion: propose_node must be called once per round!
            assert round_calls["propose"] == 2


def test_f005_idempotent_nodes_no_duplicate_proposals_or_issues():
    """F-005: Nodes must use deterministic IDs so retrying/re-invoking does not duplicate proposals or issues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_f005.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)
            controller = WorkflowController(store, lease)
            controller.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=fake_model_adapter,
            )
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )
            graph = create_workflow_graph(wf_ctx)

            # Invoke propose_node twice
            propose_fn = graph.nodes["propose"].runnable
            res1 = propose_fn.invoke({"round": 0, "run_id": state.run.id, "analyses": []})
            res2 = propose_fn.invoke({"round": 0, "run_id": state.run.id, "analyses": []})

            curr = store.load(state.run.id)
            assert len(curr.proposals) == 1, f"Expected 1 proposal, found {len(curr.proposals)}"

            # Re-invoking propose_node for round 1 generates round 1 proposal, but invoking round 1 twice does not duplicate it
            res3 = propose_fn.invoke({"round": 1, "run_id": state.run.id, "analyses": []})
            propose_fn.invoke({"round": 1, "run_id": state.run.id, "analyses": []})
            curr = store.load(state.run.id)
            assert len(curr.proposals) == 2

            # Invoke review_node twice for round 0
            review_fn = graph.nodes["review"].runnable
            review_fn.invoke({"round": 0, "run_id": state.run.id, "proposal": res1["proposal"]})
            review_fn.invoke({"round": 0, "run_id": state.run.id, "proposal": res1["proposal"]})

            curr = store.load(state.run.id)
            assert len(curr.issues) == 1, f"Expected 1 issue, found {len(curr.issues)}"

            # Re-invoking review_node for round 1
            review_fn.invoke({"round": 1, "run_id": state.run.id, "proposal": res3["proposal"]})
            review_fn.invoke({"round": 1, "run_id": state.run.id, "proposal": res3["proposal"]})
            curr = store.load(state.run.id)
            assert len(curr.issues) == 2


def test_f002_blocking_issue_resolved_by_independent_reviewer():
    """F-002: A blocking issue can be resolved through valid ChangeIssue transitions by an independent reviewer."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_f002.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)
            controller = WorkflowController(store, lease, actor="orchestration-controller")

            # Record a blocking issue
            issue = Issue(
                id="ISSUE-BLOCK-1",
                run_id=state.run.id,
                severity=IssueSeverity.BLOCKING,
                based_on_revision=0,
                claim="Missing auth mechanism",
                impact="Critical security vulnerability",
                verification_request="Verify auth tokens",
                suggested_resolution="Implement bearer tokens",
                requirement_ids=["REQ-001"],
            )
            controller.record_issue(issue)

            # Revise plan addressing the issue
            step = PlanStep(
                id="STEP-1",
                objective="Implement auth",
                requirement_ids=["REQ-001"],
                dependencies=[],
                targets=["auth.py"],
                validation="pytest",
                deliverables=["token handler"],
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
                decisions=[],
                risks=[],
                issues_addressed=["ISSUE-BLOCK-1"],
            )
            controller.commit_plan_revision(plan)

            # Attempt 1: Non-independent reviewer (actor == controller.actor) must be rejected
            with pytest.raises(Exception):
                controller.resolve_issue(
                    issue_id="ISSUE-BLOCK-1",
                    reviewer="orchestration-controller",  # Same as controller.actor!
                    review_result="PASS",
                    review_note="Self approval",
                )

            # Attempt 2: Independent reviewer succeeds
            updated = controller.resolve_issue(
                issue_id="ISSUE-BLOCK-1",
                reviewer="independent-reviewer",  # Different from controller.actor!
                review_result="PASS",
                review_note="Verified fix in plan revision 1",
            )
            resolved_issue = next(i for i in updated.issues if i.id == "ISSUE-BLOCK-1")
            assert resolved_issue.status == IssueStatus.RESOLVED
            assert resolved_issue.resolution is not None
            assert resolved_issue.resolution.review_result == "PASS"
            assert [h.status for h in resolved_issue.history] == [
                IssueStatus.OPEN,
                IssueStatus.INVESTIGATING,
                IssueStatus.PROPOSED_RESOLUTION,
                IssueStatus.RESOLVED,
            ]


def test_f002_minesweeper_fixture_resolves_blocker_and_finalizes_by_p4():
    """F-002: Minesweeper fixture run where a blocking issue is resolved via semantic review and achieves FINAL status issued by P4."""
    call_counts = {"review": 0, "synth": 0, "semantic": 0}
    recorded_issue_id: list[str] = []

    def minesweeper_model_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        nonlocal recorded_issue_id
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role=role,
                findings=["Minesweeper board model needs grid generation and mine distribution"],
                risks=["PRNG non-determinism"],
                assumptions=["9x9 board with 10 mines"],
                marker=f"{role}-marker",
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Implement Minesweeper board logic with seedable PRNG",
                alternatives=["Static board layouts"],
                tradeoffs=["Memory overhead vs flexibility"],
                requirement_coverage={"REQ-001": "Grid allocation", "REQ-002": "Mine placement"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            # Distinguish semantic review phase from initial review
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                call_counts["semantic"] += 1
                # In round 2 semantic review, resolve the blocking issue!
                curr_issues = store.load(state.run.id).issues
                target_issue = curr_issues[0].id if curr_issues else "ISSUE-0-1"
                content = ReviewOutput(
                    summary="Semantic review: verified fixes in latest plan",
                    reviewed_evidence_ids=[],
                    issues=[],
                    resolutions=[
                        IssueResolutionReport(
                            issue_id=target_issue,
                            resolution_text="Seedable PRNG verified in PlanRevision 2",
                            review_result="PASS",
                            review_note="Verified deterministic seeding implementation in STEP-2",
                        )
                    ],
                )
            else:
                call_counts["review"] += 1
                if call_counts["review"] == 1:
                    # Round 1 review raises a BLOCKING issue
                    content = ReviewOutput(
                        summary="Identified critical flaw in random distribution",
                        reviewed_evidence_ids=[],
                        issues=[
                            IssueReport(
                                claim="Mine placement lacks deterministic seed support",
                                impact="Cannot test or replay board generation",
                                severity=IssueSeverity.BLOCKING,
                                verification_request="Verify reproducibility of boards with fixed seed",
                                suggested_resolution="Accept optional seed in board generator",
                                requirement_ids=["REQ-002"],
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(
                        summary="Follow-up review: no new issues",
                        reviewed_evidence_ids=[],
                        issues=[],
                    )
        elif output_schema == SynthesizerOutput:
            call_counts["synth"] += 1
            if call_counts["synth"] == 1:
                # PlanRevision 1 does not address the issue
                content = SynthesizerOutput(
                    steps=[
                        StepDraft(
                            objective="Create 9x9 grid",
                            requirement_ids=["REQ-001", "REQ-002"],
                            dependencies=[],
                            targets=["board.py"],
                            validation="pytest test_board.py",
                            deliverables=["board.py"],
                            completion_criteria=["grid initialized"],
                            evidence_ids=[],
                        )
                    ],
                    decisions=[],
                    risks=["PRNG non-determinism"],
                    issues_addressed=[],
                    rationale="Initial naive grid",
                )
            else:
                # PlanRevision 2 addresses the blocking issue
                curr_issues = store.load(state.run.id).issues
                target_issue = curr_issues[0].id if curr_issues else "ISSUE-0-1"
                content = SynthesizerOutput(
                    steps=[
                        StepDraft(
                            objective="Create 9x9 grid with seedable PRNG",
                            requirement_ids=["REQ-001", "REQ-002"],
                            dependencies=[],
                            targets=["board.py"],
                            validation="pytest test_board.py",
                            deliverables=["board.py with seed support"],
                            completion_criteria=["grid initialized with seed"],
                            evidence_ids=[],
                        )
                    ],
                    decisions=[],
                    risks=[],
                    issues_addressed=[target_issue],
                    rationale="Addressed seed issue",
                )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "minesweeper_f002.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            state.task.requirements.append(
                Requirement(id="REQ-002", text="Mine distribution", acceptance="pass")
            )
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=minesweeper_model_adapter,
            )
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Run initial round - blocking issue will be created
            # We track the created issue ID so synthesizer and reviewer can target it dynamically
            def check_state_after_review(curr_s):
                if curr_s.issues and not recorded_issue_id:
                    recorded_issue_id.append(curr_s.issues[0].id)

            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }

            # Run workflow
            final_output = app.invoke(initial_state)

            final_state = store.load(state.run.id)
            assert final_output["gate_passed"] is True, f"Gate failed with: {final_output.get('stop_reason')}, events: {final_output.get('events')}"
            # Confirm that the blocking issue was resolved
            assert all(
                i.status == IssueStatus.RESOLVED
                for i in final_state.issues
                if i.severity == IssueSeverity.BLOCKING
            )

            # P4 Quality Service finalization
            finalization_service = FinalizationService()
            decision = finalization_service.evaluate(
                final_state,
                semantic_review=SemanticReviewAssessment(
                    passed=True,
                    reviewed_plan_revision=final_state.plan.revision,
                    feedback="Passed all criteria",
                    concerns=[],
                ),
            )
            assert decision.can_finalize is True
            assert decision.target_status == RunStatus.FINAL

            # Verify: Non-P4 actor is REJECTED when attempting to grant FINAL
            non_p4_controller = WorkflowController(store, lease, actor="rogue-worker")
            with pytest.raises(Exception):
                non_p4_controller.transition_phase(
                    final_state.run.phase, RunStatus.FINAL, reason="Attempted unauthorized finalization"
                )

            # P4 actor succeeds in issuing FINAL
            p4_controller = WorkflowController(store, lease, actor="P4-quality-service")
            p4_controller.transition_phase(
                final_state.run.phase, RunStatus.FINAL, reason=decision.reason
            )

            certified_state = store.load(state.run.id)
            assert certified_state.run.status == RunStatus.FINAL
            assert certified_state.run.phase == RunPhase.EXPORT









