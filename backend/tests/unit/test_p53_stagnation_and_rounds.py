"""Unit and integration tests for P5.3: Stagnation and max_rounds on the 11-phase graph.

Verifies 4 specific scenarios with mock LLM:
a. Blocker never resolved -> stops cleanly at max_rounds, final status PARTIAL.
b. Two consecutive rounds with the same blocker set -> triggers stagnation early, does not wait for max_rounds.
c. Blocker resolved at the final allowed round -> reaches FINAL, not cut short early.
d. SEMANTIC_REVIEW does not increment round an extra time (counts rounds by loop iteration, not by node count).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

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
from astra_multi.domain.models import (
    IssueSeverity,
    IssueStatus,
    RunPhase,
    RunStatus,
)
from astra_multi.exports.finalization import FinalizationService, SemanticReviewAssessment
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.orchestration.termination import StopReason
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.schemas import ModelResult


# ============================================================================
# Scenario A: Blocker never resolved -> stops at max_rounds with PARTIAL
# ============================================================================


def test_scenario_a_unresolved_blocker_stops_at_max_rounds_partial():
    """Scenario A: If a blocker is never resolved despite forward progress, stop at max_rounds with PARTIAL."""
    call_counts = {"synth": 0, "review": 0, "sem_review": 0}

    def adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard iterative proposal",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                call_counts["sem_review"] += 1
                # Semantic reviewer does NOT resolve the issue in any round
                content = ReviewOutput(
                    summary="Semantic review: blocker remains unresolved",
                    reviewed_evidence_ids=[],
                    issues=[],
                    resolutions=[],
                )
            else:
                call_counts["review"] += 1
                if call_counts["review"] == 1:
                    content = ReviewOutput(
                        summary="Initial review with blocker",
                        reviewed_evidence_ids=[],
                        issues=[
                            IssueReport(
                                claim="Persistent unhandled deadlock",
                                impact="Service hangs indefinitely",
                                severity=IssueSeverity.BLOCKING,
                                suggested_resolution="Implement timeout on locks",
                                requirement_ids=["REQ-001"],
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(summary="Subsequent review pass", issues=[], resolutions=[])
        elif output_schema == SynthesizerOutput:
            call_counts["synth"] += 1
            idx = call_counts["synth"]
            # In each round, introduce a NEW decision to make forward progress and avoid stagnation
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective=f"Step draft round {idx}",
                        requirement_ids=["REQ-001"],
                        validation="pytest test_code.py",
                        deliverables=["code.py"],
                        completion_criteria=["tests pass"],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question=f"Architecture choice question {idx}",
                        chosen=f"Option-{idx}",
                        rationale=f"Selected option {idx} to make progress",
                    )
                ],
                risks=[],
                issues_addressed=[],  # Blocker never addressed!
                rationale="Drafting revision",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_a.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=adapter)
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            max_rounds = 3
            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            # Assertions for Scenario A:
            # 1. Exactly max_rounds review/revise iterations were executed
            assert call_counts["synth"] == max_rounds
            assert final_output["round"] == max_rounds

            # 2. Gate failed due to max_rounds reached with unresolved blocker
            assert final_output["gate_passed"] is False
            assert StopReason.MAX_ROUNDS_REACHED.value in final_output["stop_reason"]

            # 3. Final domain state status is PARTIAL in phase EXPORT
            final_state = store.load(state.run.id)
            assert final_state.run.phase == RunPhase.EXPORT
            assert final_state.run.status == RunStatus.PARTIAL
            assert any(i.severity == IssueSeverity.BLOCKING and i.status != IssueStatus.RESOLVED for i in final_state.issues)


# ============================================================================
# Scenario B: Consecutive rounds with same blocker set -> early stagnation
# ============================================================================


def test_scenario_b_consecutive_rounds_same_blockers_triggers_stagnation_early():
    """Scenario B: Two consecutive rounds with the same blocker set and no progress triggers stagnation before max_rounds."""
    call_counts = {"synth": 0}

    def adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Static proposal without change",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                # Semantic review never resolves the issue
                content = ReviewOutput(summary="Semantic review: blocker unresolved", issues=[], resolutions=[])
            else:
                # Reviewer outputs 1 blocker on round 1, then no new issues (same blocker remains)
                if call_counts["synth"] == 0:
                    content = ReviewOutput(
                        summary="Initial review",
                        issues=[
                            IssueReport(
                                claim="Critical memory exhaustion",
                                impact="OOM crash",
                                severity=IssueSeverity.BLOCKING,
                                suggested_resolution="Set memory bounds",
                                requirement_ids=["REQ-001"],
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(summary="No new issues", issues=[], resolutions=[])
        elif output_schema == SynthesizerOutput:
            call_counts["synth"] += 1
            # Synthesizer outputs the exact same decision and step in every round (zero progress, zero new evidence)
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Static step",
                        requirement_ids=["REQ-001"],
                        validation="pytest test_code.py",
                        deliverables=["static.py"],
                        completion_criteria=["done"],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question="Same architectural question",
                        chosen="Choice A",
                        rationale="Same choice",
                    )
                ],
                risks=[],
                issues_addressed=[],  # Blocker not addressed
                rationale="Unchanged synthesis",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_b.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=adapter)
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Set max_rounds high (4) to guarantee stagnation triggers before max_rounds
            max_rounds = 4
            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            # Assertions for Scenario B:
            # 1. Stagnation was triggered after 2 consecutive rounds with identical state
            assert call_counts["synth"] == 2
            assert final_output["round"] == 2
            assert final_output["round"] < max_rounds, "Should NOT wait for max_rounds (4)"

            # 2. Gate failed with stagnation detected
            assert final_output["gate_passed"] is False
            assert StopReason.STAGNATION_DETECTED.value in final_output["stop_reason"]

            # 3. Final domain state status is PARTIAL
            final_state = store.load(state.run.id)
            assert final_state.run.phase == RunPhase.EXPORT
            assert final_state.run.status == RunStatus.PARTIAL


# ============================================================================
# Scenario C: Blocker resolved at final allowed round -> FINAL (not cut short)
# ============================================================================


def test_scenario_c_blocker_resolved_at_final_allowed_round_reaches_final():
    """Scenario C: Blocker resolved at the final allowed round passes gate and achieves FINAL status without early termination."""
    call_counts = {"synth": 0}

    def adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Iterative refinement approach",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                # Resolve the blocker ONLY on round 3 (the last allowed round)
                curr_issues = store.load(state.run.id).issues
                target_issue = curr_issues[0].id if curr_issues else "ISSUE-1"
                if call_counts["synth"] >= 3:
                    content = ReviewOutput(
                        summary="Semantic review: verified resolution of blocker in final round",
                        reviewed_evidence_ids=[],
                        issues=[],
                        resolutions=[
                            IssueResolutionReport(
                                issue_id=target_issue,
                                resolution_text="Verified fix in revision 3",
                                review_result="PASS",
                                review_note="Verified and resolved",
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(summary="Blocker not yet resolved", issues=[], resolutions=[])
            else:
                if call_counts["synth"] == 0:
                    content = ReviewOutput(
                        summary="Initial review with blocking issue",
                        issues=[
                            IssueReport(
                                claim="Critical missing authorization check",
                                impact="Privilege escalation",
                                severity=IssueSeverity.BLOCKING,
                                suggested_resolution="Enforce RBAC role check",
                                requirement_ids=["REQ-001"],
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(summary="No new issues", issues=[], resolutions=[])
        elif output_schema == SynthesizerOutput:
            call_counts["synth"] += 1
            idx = call_counts["synth"]
            curr_issues = store.load(state.run.id).issues
            target_issue = [curr_issues[0].id] if (curr_issues and idx >= 3) else []
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective=f"Step revision {idx}",
                        requirement_ids=["REQ-001"],
                        validation="pytest test_auth.py",
                        deliverables=["auth.py"],
                        completion_criteria=["tests pass"],
                    )
                ],
                decisions=[
                    DecisionDraft(
                        question=f"Auth decision {idx}",
                        chosen=f"RBAC-v{idx}",
                        rationale="Progressive refinement",
                    )
                ],
                risks=[],
                issues_addressed=target_issue,  # Addressed on round 3
                rationale="Synthesizing revision",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_c.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="quality-service", ttl=60)
            # Use P4-quality-service actor so export_node can issue FINAL directly upon passing gate
            controller = WorkflowController(store, lease, actor="P4-quality-service")
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=adapter)
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            max_rounds = 3
            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }
            final_output = app.invoke(initial_state)

            # Assertions for Scenario C:
            # 1. Exactly max_rounds (3) were executed - NOT cut short at round 1 or 2
            assert call_counts["synth"] == max_rounds
            assert final_output["round"] == max_rounds

            # 2. Gate passed at the final allowed round
            assert final_output["gate_passed"] is True

            # 3. All blocking issues are resolved
            final_state = store.load(state.run.id)
            assert all(i.status == IssueStatus.RESOLVED for i in final_state.issues if i.severity == IssueSeverity.BLOCKING)

            # 4. Final state achieved RunStatus.FINAL in phase EXPORT
            assert final_state.run.phase == RunPhase.EXPORT
            assert final_state.run.status == RunStatus.FINAL

            # 5. Finalization service confirms eligibility for FINAL
            finalization_service = FinalizationService()
            decision = finalization_service.evaluate(
                final_state,
                semantic_review=SemanticReviewAssessment(
                    passed=True,
                    reviewed_plan_revision=final_state.plan.revision,
                    feedback="Passed all checks",
                    concerns=[],
                ),
            )
            assert decision.can_finalize is True
            assert decision.target_status == RunStatus.FINAL


# ============================================================================
# Scenario D: SEMANTIC_REVIEW does not increment round
# ============================================================================


def test_scenario_d_semantic_review_does_not_increment_round():
    """Scenario D: SEMANTIC_REVIEW node does not increment round; rounds are counted per loop iteration, not per node."""
    decision_idx = {"count": 0}

    def adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["OK"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard proposal",
                alternatives=[],
                tradeoffs=[],
                requirement_coverage={"REQ-001": "Coverage"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                content = ReviewOutput(summary="Semantic review pass", issues=[], resolutions=[])
            else:
                content = ReviewOutput(
                    summary="Review pass with blocker",
                    issues=[
                        IssueReport(
                            claim="Blocking issue needing second round",
                            impact="High",
                            severity=IssueSeverity.BLOCKING,
                            suggested_resolution="Fix blocker in revision 2",
                            requirement_ids=["REQ-001"],
                        )
                    ],
                )
        elif output_schema == SynthesizerOutput:
            decision_idx["count"] += 1
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Step 1",
                        requirement_ids=["REQ-001"],
                        validation="pytest",
                        deliverables=["main.py"],
                        completion_criteria=["tests pass"],
                    )
                ],
                decisions=[
                    DecisionDraft(question=f"Q-{decision_idx['count']}", chosen="C", rationale="R")
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
            usage={"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_d.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=adapter)
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute via app.stream to capture each node's state delta
            stream_chunks = list(app.stream({
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 2,
                "events": [],
            }))

            # Extract outputs from revise and semantic_review nodes
            revise_outputs = [chunk["revise"] for chunk in stream_chunks if "revise" in chunk]
            semantic_outputs = [chunk["semantic_review"] for chunk in stream_chunks if "semantic_review" in chunk]

            # 1. revise ran 2 times, and set round to 1 on iteration 1, and 2 on iteration 2
            assert len(revise_outputs) == 2
            assert revise_outputs[0]["round"] == 1
            assert revise_outputs[1]["round"] == 2

            # 2. semantic_review ran 2 times, and its output NEVER contains 'round'
            assert len(semantic_outputs) == 2
            for out in semantic_outputs:
                assert "round" not in out, "semantic_review must NOT return 'round' (rounds count by loop iteration)"

            # 3. Final round in completed state is exactly 2, not 3 or 4
            assert revise_outputs[-1]["round"] == 2

            # Verify the node execution sequence: each iteration executes revise then semantic_review
            executed_nodes = [list(chunk.keys())[0] for chunk in stream_chunks]
            loop_nodes = [n for n in executed_nodes if n in ("revise", "semantic_review")]
            assert loop_nodes == ["revise", "semantic_review", "revise", "semantic_review"]


