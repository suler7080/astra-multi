"""Integration tests for the LangGraph multi-agent discussion workflow (P3.3)."""

import tempfile
from pathlib import Path
from typing import Any

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
)
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import IssueSeverity, Requirement, RunPhase, RunStatus
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
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


