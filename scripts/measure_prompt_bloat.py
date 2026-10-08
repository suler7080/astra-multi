#!/usr/bin/env python3
"""Measure prompt token counts across 5 rounds for Minesweeper fixture.

P5.4 requirement 1:
Đo trước: viết test/script ghi số token của prompt từng tác nhân
(Planner, Reviewer, Synthesizer) qua 5 vòng với fixture Minesweeper kéo dài.
Lưu số liệu BEFORE.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

repo_root = Path(__file__).resolve().parent.parent
backend_src = repo_root / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

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
)
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    IssueStatus,
    Requirement,
    RunPhase,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    ContextBuilder,
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


def run_5round_measurement() -> list[dict]:
    recorded_calls: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "ms_5rounds.db"
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

            def adapter(
                provider: str,
                role: str,
                messages: list[dict[str, str]],
                output_schema: any = None,
                **kwargs: any,
            ) -> ModelResult:
                full_prompt_text = "".join(m.get("content", "") for m in messages)
                tok_count = max(1, len(full_prompt_text.encode("utf-8")) // 4)
                char_count = len(full_prompt_text)

                round_synth_count = len([c for c in recorded_calls if c["schema"] == "SynthesizerOutput"])
                current_round_num = round_synth_count

                call_record = {
                    "round": current_round_num,
                    "role": role,
                    "schema": output_schema.__name__ if output_schema else "None",
                    "tokens": tok_count,
                    "chars": char_count,
                }
                recorded_calls.append(call_record)

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
                            # Earlier rounds: resolve the warning issue that was addressed in this round
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

            final_run = store.load(state.run.id).run
            print(f"Workflow Finished: phase={final_run.phase.value}, status={final_run.status.value}, gate_passed={final_state.get('gate_passed')}")

    return recorded_calls


if __name__ == "__main__":
    calls = run_5round_measurement()
    print("\n" + "=" * 80)
    print("CHI TIẾT LỜI GỌI MODEL QUA 5 VÒNG (PROMPT TOKENS & CHARS)")
    print("=" * 80)
    header = f"{'Idx':>3} | {'Round':>5} | {'Role':<12} | {'Schema':<22} | {'Tokens':>7} | {'Chars':>8}"
    print(header)
    print("-" * len(header))
    for i, c in enumerate(calls, 1):
        print(f"{i:3d} | {c['round']:5d} | {c['role']:<12} | {c['schema']:<22} | {c['tokens']:7d} | {c['chars']:8d}")

    # Summary by round and role
    print("\n" + "=" * 80)
    print("BẢNG TỔNG HỢP TOKEN THEO TỪNG VÒNG & VAI TRÒ")
    print("=" * 80)
    print(f"{'Round':>5} | {'Planner (propose)':>18} | {'Reviewer (review)':>18} | {'Synthesizer':>15} | {'Reviewer (semantic)':>20} | {'Total Round':>12}")
    print("-" * 100)

    rounds = sorted(set(c["round"] for c in calls))
    for r in rounds:
        r_calls = [c for c in calls if c["round"] == r]
        p_tok = next((c["tokens"] for c in r_calls if c["role"] == "planner" and c["schema"] == "ProposalOutput"), 0)
        s_tok = next((c["tokens"] for c in r_calls if c["role"] == "synthesizer"), 0)
        rev_calls = [c for c in r_calls if c["role"] == "reviewer" and c["schema"] == "ReviewOutput"]
        r_init_tok = rev_calls[0]["tokens"] if len(rev_calls) >= 1 else 0
        r_sem_tok = rev_calls[1]["tokens"] if len(rev_calls) >= 2 else 0
        tot = sum(c["tokens"] for c in r_calls)
        print(f"{r + 1:5d} | {p_tok:18d} | {r_init_tok:18d} | {s_tok:15d} | {r_sem_tok:20d} | {tot:12d}")
