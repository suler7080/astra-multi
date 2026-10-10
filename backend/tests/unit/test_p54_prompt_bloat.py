"""Unit tests for P5.4: Prompt bloat reduction and round-based context bundles.

Verifies:
1. (i) Prompt token count at round 5 is significantly reduced compared to BEFORE baseline.
2. (ii) Minesweeper fixture successfully completes with status FINAL and gate_passed=True.
3. (iii) Unresolved issues are present in Reviewer prompts at every round.
4. Context isolation is strictly preserved in INDEPENDENT_ANALYSIS.
5. Deterministic count-based summarization for older model calls and events history.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

import pytest

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    IssueResolutionReport,
    IssueSeverity,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
    format_independent_analysis_prompt,
)
from astra_multi.context.bundle import ContextBuilder, ContextLimits, orchestration_limits
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    Issue,
    IssueResolution,
    IssueStatus,
    ModelCall,
    Requirement,
    RunPhase,
    RunStatus,
    utc_now,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


def test_p54_minesweeper_5rounds_bloat_reduction_and_final():
    """Requirement 4:

    (i) Token prompt round 5 decreases significantly compared to BEFORE.
    (ii) Minesweeper result is FINAL.
    (iii) Unresolved issues are always present in Reviewer prompt at every round.
    """
    recorded_calls: list[dict[str, Any]] = []

    def adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        full_prompt_text = "".join(m.get("content", "") for m in messages)
        tok_count = max(1, len(full_prompt_text.encode("utf-8")) // 4)

        round_synth_count = len([c for c in recorded_calls if c["schema"] == "SynthesizerOutput"])
        current_round_num = round_synth_count

        recorded_calls.append({
            "round": current_round_num,
            "role": role,
            "schema": output_schema.__name__ if output_schema else "None",
            "tokens": tok_count,
            "prompt_text": full_prompt_text,
        })

        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role=role,
                findings=["Minesweeper board model needs grid generation and mine distribution"],
                risks=["PRNG non-determinism"],
                assumptions=["9x9 board with 10 mines"],
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach=f"Implement Minesweeper board logic with seedable PRNG (round {current_round_num})",
                alternatives=["Static board layouts"],
                tradeoffs=["Memory overhead vs flexibility"],
                requirement_coverage={"REQ-001": "Grid allocation", "REQ-002": "Mine placement"},
                claim_ids=[],
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if is_semantic:
                if current_round_num >= 4:
                    # Final round (round 5): resolve all remaining issues
                    curr_issues = store.load(state.run.id).issues
                    open_issues = [i for i in curr_issues if i.status != IssueStatus.RESOLVED]
                    resolutions = [
                        IssueResolutionReport(
                            issue_id=i.id,
                            resolution_text=f"Resolved {i.id} in Plan revision 5",
                            review_result="PASS",
                            review_note="Verified deterministic fix in latest plan revision",
                        )
                        for i in open_issues
                    ]
                    content = ReviewOutput(
                        summary="Semantic review: all issues verified and resolved",
                        issues=[],
                        resolutions=resolutions,
                    )
                else:
                    # Earlier rounds: resolve the warning issue
                    curr_issues = store.load(state.run.id).issues
                    resolutions = []
                    for i in curr_issues:
                        if i.severity == IssueSeverity.WARNING and i.status != IssueStatus.RESOLVED:
                            resolutions.append(
                                IssueResolutionReport(
                                    issue_id=i.id,
                                    resolution_text=f"Resolved warning {i.id}",
                                    review_result="PASS",
                                    review_note="Verified in plan",
                                )
                            )
                    content = ReviewOutput(
                        summary=f"Semantic review round {current_round_num}: blocker remains open",
                        issues=[],
                        resolutions=resolutions,
                    )
            else:
                # Initial review for each round
                if current_round_num == 0:
                    content = ReviewOutput(
                        summary="Initial review: blocking issue on PRNG seed",
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
                elif current_round_num == 1:
                    content = ReviewOutput(
                        summary="Review round 2: warning issue on grid dimensions",
                        issues=[
                            IssueReport(
                                claim="Grid dimensions hardcoded to 9x9 without configuration",
                                impact="Cannot support intermediate/expert difficulties",
                                severity=IssueSeverity.WARNING,
                                verification_request="Check width/height params",
                                suggested_resolution="Expose width and height parameters",
                                requirement_ids=["REQ-001"],
                            )
                        ],
                    )
                elif current_round_num == 2:
                    content = ReviewOutput(
                        summary="Review round 3: warning issue on cell reveal recursion",
                        issues=[
                            IssueReport(
                                claim="Cell reveal recursion might cause stack overflow",
                                impact="Crashes on large empty minefield cascades",
                                severity=IssueSeverity.WARNING,
                                verification_request="Check iterative BFS implementation",
                                suggested_resolution="Use queue-based flood fill",
                                requirement_ids=["REQ-001"],
                            )
                        ],
                    )
                elif current_round_num == 3:
                    content = ReviewOutput(
                        summary="Review round 4: warning issue on flag boundary condition",
                        issues=[
                            IssueReport(
                                claim="Flagging count does not bound at total mine count",
                                impact="Player can place unlimited flags",
                                severity=IssueSeverity.WARNING,
                                verification_request="Check flag bounds check",
                                suggested_resolution="Decrement remaining flags counter",
                                requirement_ids=["REQ-002"],
                            )
                        ],
                    )
                else:
                    content = ReviewOutput(summary="Review round 5: no new issues found", issues=[])
        elif output_schema == SynthesizerOutput:
            curr_issues = store.load(state.run.id).issues
            open_warnings = [
                i.id for i in curr_issues
                if i.severity == IssueSeverity.WARNING and i.status != IssueStatus.RESOLVED
            ]

            addressed = []
            if current_round_num >= 4:
                addressed = [i.id for i in curr_issues if i.status != IssueStatus.RESOLVED]
            else:
                addressed = open_warnings

            steps = [
                StepDraft(
                    objective=f"Step 1: Board representation (round {current_round_num + 1})",
                    requirement_ids=["REQ-001", "REQ-002"],
                    targets=["board.py"],
                    validation="pytest test_board.py",
                    deliverables=[f"board_v{current_round_num + 1}.py"],
                    completion_criteria=["tests pass"],
                )
            ]
            decisions = [
                DecisionDraft(
                    question=f"PRNG algorithm selection round {current_round_num + 1}",
                    chosen=f"Mersenne Twister with seed support (rev {current_round_num + 1})",
                    rationale=f"Standard reproducible PRNG algorithm for round {current_round_num + 1}",
                )
            ]
            content = SynthesizerOutput(
                steps=steps,
                decisions=decisions,
                risks=[],
                issues_addressed=addressed,
                rationale=f"Synthesis plan for round {current_round_num + 1}",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"prompt_tokens": tok_count, "completion_tokens": 50, "total_tokens": tok_count + 50},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "ms_test.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            state.task.requirements.append(
                Requirement(id="REQ-002", text="Mine distribution and deterministic PRNG seed", acceptance="pass")
            )
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="P4-quality-service", ttl=300)
            controller = WorkflowController(store, lease, actor="P4-quality-service")
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=adapter)
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            final_state = app.invoke(
                {
                    "run_id": state.run.id,
                    "round": 0,
                    "max_rounds": 5,
                    "events": [],
                },
                config={"recursion_limit": 100},
            )

            # (ii) Assert Minesweeper outcome is FINAL and gate passed
            assert final_state.get("gate_passed") is True
            final_run = store.load(state.run.id).run
            assert final_run.phase == RunPhase.EXPORT
            assert final_run.status == RunStatus.FINAL

            # (i) Assert token prompt round 5 decreases significantly compared to BEFORE
            # BEFORE metrics for Round 5:
            # - Planner (propose): 1,037 tokens
            # - Reviewer (review): 1,305 tokens
            # - Synthesizer: 1,373 tokens
            # - Reviewer (semantic review final): 1,754 tokens
            round_5_calls = [c for c in recorded_calls if c["round"] == 4]
            p_call = next(c for c in round_5_calls if c["role"] == "planner")
            s_call = next(c for c in round_5_calls if c["role"] == "synthesizer")
            rev_calls = [c for c in round_5_calls if c["role"] == "reviewer"]
            sem_review_r4_plan = rev_calls[0]  # semantic review on plan 4
            review_r5 = rev_calls[1]           # review on proposal 5
            final_sem_call = recorded_calls[-1]

            # Verify substantial reduction:
            # Planner BEFORE: 1037 -> AFTER: 855
            assert p_call["tokens"] < 1037, f"Planner tokens {p_call['tokens']} should be < 1037"
            assert p_call["tokens"] <= 900
            # Reviewer review BEFORE: 1305 -> AFTER: 918
            assert review_r5["tokens"] < 1305, f"Reviewer tokens {review_r5['tokens']} should be < 1305"
            assert review_r5["tokens"] <= 1000
            # Reviewer semantic review BEFORE: 1641 -> AFTER: 1057
            assert sem_review_r4_plan["tokens"] < 1641
            assert sem_review_r4_plan["tokens"] <= 1200
            # Synthesizer BEFORE: 1373 -> AFTER: 976
            assert s_call["tokens"] < 1373, f"Synthesizer tokens {s_call['tokens']} should be < 1373"
            assert s_call["tokens"] <= 1050
            # Final semantic review BEFORE: 1754 -> AFTER: 1074
            assert final_sem_call["tokens"] < 1754, f"Final semantic review tokens {final_sem_call['tokens']} should be < 1754"
            assert final_sem_call["tokens"] <= 1200

            # (iii) Assert unresolved issues are in Reviewer prompts at EVERY round
            reviewer_calls = [c for c in recorded_calls if c["role"] == "reviewer"]
            # The initial blocker was created in round 0 review; in all subsequent reviewer calls (rounds 1..4),
            # the unresolved blocker issue must be present in the prompt
            for call in reviewer_calls[2:]:
                assert "deterministic seed" in call["prompt_text"], (
                    f"Unresolved issue missing from reviewer prompt in round {call['round']}"
                )



def test_p54_context_isolation_independent_analysis():
    """Requirement 3: Context isolation is strictly preserved in INDEPENDENT_ANALYSIS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir))
        builder = ContextBuilder(art_store)
        state = sample_state(repo=False)

        planner_bundle = builder.build_context(
            run=state,
            role="planner",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=orchestration_limits(),
            round_num=0,
        )
        reviewer_bundle = builder.build_context(
            run=state,
            role="reviewer",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=orchestration_limits(),
            round_num=0,
        )

        assert "plan" not in planner_bundle.content
        assert "proposal" not in planner_bundle.content
        assert "open_issues" not in planner_bundle.content
        assert "plan" not in reviewer_bundle.content
        assert "proposal" not in reviewer_bundle.content
        assert "open_issues" not in reviewer_bundle.content

        # Messages format cleanly
        p_msgs = format_independent_analysis_prompt(planner_bundle)
        assert any("INDEPENDENT_ANALYSIS" in m["content"] for m in p_msgs)


def test_p54_bundle_round_fields_and_deterministic_history_summary():
    """Requirement 2: Context bundle retains (a) plan & proposal, (b) open issues,

    (c) closed resolutions, and deterministically summarizes older model_calls & events.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        art_store = FileArtifactStore(Path(tmpdir))
        builder = ContextBuilder(art_store)
        state = sample_state(repo=False)

        # Add open issue and closed issue with resolution
        open_issue = Issue(
            id="ISSUE-OPEN-1",
            run_id=state.run.id,
            based_on_revision=0,
            severity=IssueSeverity.BLOCKING,
            claim="Open blocking claim",
            impact="High impact",
            suggested_resolution="Fix this",
            verification_request="Verify open",
        )
        closed_issue = Issue(
            id="ISSUE-CLOSED-1",
            run_id=state.run.id,
            based_on_revision=0,
            severity=IssueSeverity.WARNING,
            status=IssueStatus.RESOLVED,
            claim="Closed warning claim",
            impact="Low impact",
            suggested_resolution="Fixed previously",
            verification_request="Verify closed",
            resolution=IssueResolution(
                text="Resolved in revision 1",
                review_result="PASS",
                review_note="All clear",
            ),
        )
        state.issues.extend([open_issue, closed_issue])

        # Add older model calls (round 0) and recent model call (round 2)
        call_r0 = ModelCall(
            id="CALL-TEST-0",
            run_id=state.run.id,
            role="planner",
            provider="fake",
            model_id="fake-m",
            prompt_version="v1.0",
            input_hash="0" * 64,
            usage={"total_tokens": 500},
        )
        call_r2 = ModelCall(
            id="CALL-TEST-2",
            run_id=state.run.id,
            role="reviewer",
            provider="fake",
            model_id="fake-m",
            prompt_version="v1.0",
            input_hash="0" * 64,
            usage={"total_tokens": 600},
        )
        state.model_calls.extend([call_r0, call_r2])

        events = [
            "[INTAKE] Started run",
            "[SNAPSHOT] Snapshot verified",
            "[GATE] Round 0 gate check",
            "[PROPOSE] Round 1 proposal",
            "[GATE] Round 1 gate check",
            "[PROPOSE] Round 2 proposal",
        ]

        # Build context for round 2 with recent_full_rounds=1
        bundle = builder.build_context(
            run=state,
            role="planner",
            phase=RunPhase.PROPOSE,
            refs=[],
            limits=orchestration_limits(),
            round_num=2,
            events=events,
            recent_full_rounds=1,
        )

        bundle_data = json.loads(bundle.content)

        # (a) Plan and proposal present
        assert "plan" in bundle_data
        assert "proposal" in bundle_data

        # (b) Open issues present
        assert "open_issues" in bundle_data
        assert any(i["id"] == "ISSUE-OPEN-1" for i in bundle_data["open_issues"])

        # (c) Closed resolutions present
        assert "closed_resolutions" in bundle_data
        closed_rec = next(c for c in bundle_data["closed_resolutions"] if c["issue_id"] == "ISSUE-CLOSED-1")
        assert closed_rec["status"] == "resolved"
        assert closed_rec["resolution"]["text"] == "Resolved in revision 1"

        # Deterministic summary of older model calls
        assert "recent_model_calls" in bundle_data
        assert any(c["call"] == "CALL-TEST-2" for c in bundle_data["recent_model_calls"])
        assert "prior_model_calls_summary" in bundle_data
        assert bundle_data["prior_model_calls_summary"]["call_count"] == 1
        assert bundle_data["prior_model_calls_summary"]["total_tokens"] == 500
