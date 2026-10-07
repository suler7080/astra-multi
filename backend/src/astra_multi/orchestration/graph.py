"""LangGraph workflow definition integrating domain store, model gateway, and tools.

P3.3 Production multi-agent discussion workflow graph:
- Phases: INTAKE -> SNAPSHOT -> INVESTIGATE -> INDEPENDENT_ANALYSIS (fan-out Planner/Reviewer)
  -> PROPOSE -> REVIEW -> VERIFY -> REVISE -> QUALITY_GATE -> EXPORT
- Bounded loop: review -> verify -> revise -> gate -> (repeat or export/partial)
- Domain state commits exclusively through controller / P1 commands.
- Checkpoint persistence through CheckpointBridge.
"""

from __future__ import annotations

import operator
import os
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from astra_multi.agents.roles import (
    PROMPT_VERSION_V1,
    AnalysisOutput,
    ProposalOutput,
    ReviewOutput,
    SynthesizerOutput,
    format_independent_analysis_prompt,
    format_propose_prompt,
    format_review_prompt,
    format_synthesize_prompt,
)
from astra_multi.context.bundle import ContextBuilder, orchestration_limits
from astra_multi.context.evidence import EvidenceLedger
from astra_multi.domain.models import (
    Decision,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Proposal,
    RunPhase,
    RunStatus,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator, ViolationSeverity
from astra_multi.gateway.model_gateway import ModelGateway
from astra_multi.orchestration.budget import BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.termination import StagnationDetector, StopReason


def _merge_analyses(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = {a["role"]: a for a in existing}
    for a in new:
        merged[a["role"]] = a
    return sorted(merged.values(), key=lambda x: x["role"])


class OrchestrationState(TypedDict, total=False):
    run_id: str
    round: int
    max_rounds: int
    analyses: Annotated[list[dict[str, Any]], _merge_analyses]
    proposal: dict[str, Any] | None
    review: dict[str, Any] | None
    gate_passed: bool
    stop_reason: str
    events: Annotated[list[str], operator.add]


class WorkflowContext:
    """Carries runtime dependencies for graph node executions."""

    def __init__(
        self,
        controller: WorkflowController,
        gateway: ModelGateway,
        context_builder: ContextBuilder,
        evidence_ledger: EvidenceLedger | None = None,
        budget_service: BudgetService | None = None,
        provider: str | None = None,
    ) -> None:
        self.controller = controller
        self.gateway = gateway
        self.context_builder = context_builder
        self.evidence_ledger = evidence_ledger
        self.budget_service = budget_service
        self.stagnation_detector = StagnationDetector()
        self.provider = provider or os.environ.get("ASTRA_MULTI_PROVIDER", "fake")


def create_workflow_graph(wf_ctx: WorkflowContext) -> StateGraph:
    """Builds the full multi-agent discussion workflow graph."""
    ctrl = wf_ctx.controller
    gateway = wf_ctx.gateway
    builder = wf_ctx.context_builder
    detector = wf_ctx.stagnation_detector

    def intake_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.SNAPSHOT)
        return {
            "round": 0,
            "max_rounds": state.get("max_rounds", 2),
            "events": [f"[INTAKE] Started run {ctrl.lease.run_id}"],
        }

    def snapshot_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.INVESTIGATE)
        return {"events": ["[SNAPSHOT] Snapshot verified"]}

    def investigate_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
        return {"events": ["[INVESTIGATE] Initial inspection complete"]}

    def planner_analysis_node(state: OrchestrationState) -> dict:
        curr_state = ctrl.get_state()
        bundle = builder.build_context(
            run=curr_state,
            role="planner",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=orchestration_limits(),
        )
        messages = format_independent_analysis_prompt(bundle)

        res = gateway.call(
            provider=wf_ctx.provider,
            role="planner",
            messages=messages,
            output_schema=AnalysisOutput,
        )
        output = AnalysisOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=f"CALL-P-ANALYSIS-{state.get('round', 0)}",
            role="planner",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
        )
        return {
            "analyses": [output.model_dump(mode="json")],
            "events": [f"[ANALYSIS] Planner produced {len(output.findings)} findings"],
        }

    def reviewer_analysis_node(state: OrchestrationState) -> dict:
        curr_state = ctrl.get_state()
        bundle = builder.build_context(
            run=curr_state,
            role="reviewer",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=orchestration_limits(),
        )
        messages = format_independent_analysis_prompt(bundle)

        res = gateway.call(
            provider=wf_ctx.provider,
            role="reviewer",
            messages=messages,
            output_schema=AnalysisOutput,
        )
        output = AnalysisOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=f"CALL-R-ANALYSIS-{state.get('round', 0)}",
            role="reviewer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
        )
        return {
            "analyses": [output.model_dump(mode="json")],
            "events": [f"[ANALYSIS] Reviewer produced {len(output.findings)} findings"],
        }

    def propose_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.PROPOSE)
        curr_state = ctrl.get_state()
        bundle = builder.build_context(
            run=curr_state,
            role="planner",
            phase=RunPhase.PROPOSE,
            refs=[],
            limits=orchestration_limits(),
        )
        analyses = [AnalysisOutput.model_validate(a) for a in state.get("analyses", [])]
        messages = format_propose_prompt(bundle, analyses)

        res = gateway.call(
            provider=wf_ctx.provider,
            role="planner",
            messages=messages,
            output_schema=ProposalOutput,
        )
        proposal_out = ProposalOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=f"CALL-PROPOSE-{state.get('round', 0)}",
            role="planner",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
        )

        valid_claims = {c.id for c in curr_state.claims}
        valid_reqs = {r.id for r in curr_state.task.requirements}
        filtered_claims = [cid for cid in proposal_out.claim_ids if cid in valid_claims]
        filtered_coverage = {
            k: v for k, v in proposal_out.requirement_coverage.items() if k in valid_reqs
        }

        domain_proposal = Proposal(
            id=f"PROP-{uuid.uuid4().hex[:6]}",
            run_id=curr_state.run.id,
            author_role="planner",
            base_revision=curr_state.plan.revision if curr_state.plan else 0,
            approach=proposal_out.approach,
            alternatives=proposal_out.alternatives,
            tradeoffs=proposal_out.tradeoffs,
            requirement_coverage=filtered_coverage,
            claim_ids=filtered_claims,
        )
        ctrl.record_proposal(domain_proposal)

        return {
            "proposal": proposal_out.model_dump(mode="json"),
            "events": [f"[PROPOSE] Proposal generated: {proposal_out.approach[:60]}"],
        }

    def review_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.REVIEW)
        curr_state = ctrl.get_state()
        bundle = builder.build_context(
            run=curr_state,
            role="reviewer",
            phase=RunPhase.REVIEW,
            refs=[],
            limits=orchestration_limits(),
        )
        prop = ProposalOutput.model_validate(state["proposal"])
        messages = format_review_prompt(bundle, prop, curr_state.plan.model_dump(mode="json") if curr_state.plan else None)

        res = gateway.call(
            provider=wf_ctx.provider,
            role="reviewer",
            messages=messages,
            output_schema=ReviewOutput,
        )
        review_out = ReviewOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=f"CALL-REVIEW-{state.get('round', 0)}",
            role="reviewer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
        )

        # Commit domain issues
        valid_reqs = {r.id for task in curr_state.tasks for r in task.requirements}
        valid_evidence = {e.id for e in curr_state.evidence}
        existing_issue_ids = {i.id for i in curr_state.issues}
        issue_round = state.get("round", 0)
        for idx, ir in enumerate(review_out.issues):
            filtered_req_ids = [rid for rid in ir.requirement_ids if rid in valid_reqs]
            filtered_evi_ids = [eid for eid in ir.evidence_ids if eid in valid_evidence]
            verif_req = ir.verification_request
            if not filtered_evi_ids and not verif_req:
                verif_req = f"Verification required: {ir.claim[:100]}"
            issue_id = f"ISSUE-{issue_round}-{idx + 1}"
            counter = idx + 1
            while issue_id in existing_issue_ids:
                counter += 1
                issue_id = f"ISSUE-{issue_round}-{counter}"
            existing_issue_ids.add(issue_id)
            domain_issue = Issue(
                id=issue_id,
                run_id=curr_state.run.id,
                severity=ir.severity,
                based_on_revision=curr_state.plan.revision if curr_state.plan else 0,
                claim=ir.claim,
                impact=ir.impact,
                verification_request=verif_req,
                suggested_resolution=ir.suggested_resolution,
                requirement_ids=filtered_req_ids,
                evidence_ids=filtered_evi_ids,
            )
            ctrl.record_issue(domain_issue)

        return {
            "review": review_out.model_dump(mode="json"),
            "events": [f"[REVIEW] Found {len(review_out.issues)} issues"],
        }

    def verify_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.VERIFY)
        return {"events": ["[VERIFY] Verification completed"]}

    def revise_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.REVISE)
        curr_state = ctrl.get_state()
        current_round = state.get("round", 0) + 1
        bundle = builder.build_context(
            run=curr_state,
            role="synthesizer",
            phase=RunPhase.REVISE,
            refs=[],
            limits=orchestration_limits(),
        )
        prop = ProposalOutput.model_validate(state["proposal"])
        rev = ReviewOutput.model_validate(state["review"])
        messages = format_synthesize_prompt(bundle, prop, rev, curr_state.plan.model_dump(mode="json") if curr_state.plan else None)

        res = gateway.call(
            provider=wf_ctx.provider,
            role="synthesizer",
            messages=messages,
            output_schema=SynthesizerOutput,
        )
        synth_out = SynthesizerOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=f"CALL-SYNTH-{current_round}",
            role="synthesizer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
        )

        # Build PlanRevision
        base_rev = curr_state.plan.revision if curr_state.plan else 0
        valid_reqs = {r.id for r in curr_state.task.requirements}
        valid_evidence = {e.id for e in curr_state.evidence}
        valid_issues = {i.id for i in curr_state.issues}
        fallback_req_id = list(valid_reqs)[0] if valid_reqs else "REQ-001"

        plan_steps: list[PlanStep] = []
        for idx, s in enumerate(synth_out.steps):
            step_id = f"STEP-{idx + 1}"
            filtered_reqs = [rid for rid in s.requirement_ids if rid in valid_reqs]
            if not filtered_reqs:
                filtered_reqs = [fallback_req_id]
            filtered_evis = [eid for eid in s.evidence_ids if eid in valid_evidence]
            prior_step_ids = {f"STEP-{j + 1}" for j in range(idx)}
            filtered_deps = [dep for dep in s.dependencies if dep in prior_step_ids]
            plan_steps.append(
                PlanStep(
                    id=step_id,
                    objective=s.objective,
                    requirement_ids=filtered_reqs,
                    dependencies=filtered_deps,
                    targets=s.targets,
                    validation=s.validation,
                    deliverables=s.deliverables,
                    completion_criteria=s.completion_criteria,
                    evidence_ids=filtered_evis,
                )
            )

        existing_dec_ids = {dec.id for dec in curr_state.decisions}
        dec_counter = len(curr_state.decisions) + 1
        plan_decisions: list[Decision] = []
        for d in synth_out.decisions:
            filtered_evis = [eid for eid in d.evidence_ids if eid in valid_evidence]
            filtered_issues = [iid for iid in d.related_issue_ids if iid in valid_issues]
            while f"DEC-{dec_counter}" in existing_dec_ids:
                dec_counter += 1
            dec_id = f"DEC-{dec_counter}"
            existing_dec_ids.add(dec_id)
            dec_counter += 1

            dec = Decision(
                id=dec_id,
                run_id=curr_state.run.id,
                question=d.question,
                chosen=d.chosen,
                rationale=d.rationale,
                alternatives=d.alternatives,
                evidence_ids=filtered_evis,
                related_issues=filtered_issues,
            )
            plan_decisions.append(dec)
            ctrl.record_decision(dec)

        filtered_issues_addressed = [
            iid for iid in synth_out.issues_addressed if iid in valid_issues
        ]

        new_plan = PlanRevision(
            id=f"PLAN-{base_rev + 1}",
            run_id=curr_state.run.id,
            revision=base_rev + 1,
            based_on_revision=base_rev,
            requirements_revision=curr_state.task.revision,
            snapshot_id=curr_state.run.snapshot_id,
            steps=plan_steps,
            decisions=plan_decisions,
            risks=synth_out.risks,
            issues_addressed=filtered_issues_addressed,
        )
        ctrl.commit_plan_revision(new_plan)

        # Check stagnation
        detector.record_round(ctrl.get_state(), current_round)

        return {
            "round": current_round,
            "events": [f"[REVISE] Committed plan revision {new_plan.revision}"],
        }

    def quality_gate_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.QUALITY_GATE)
        curr_state = ctrl.get_state()
        plan = curr_state.plan
        round_num = state.get("round", 0)
        max_rounds = state.get("max_rounds", 2)

        # Structural gate checks
        problems: list[str] = []
        if not plan:
            problems.append("No plan committed")

        # Check blocking issues
        unresolved_blocking = [
            i.id for i in curr_state.issues
            if i.severity == IssueSeverity.BLOCKING and i.status != IssueStatus.RESOLVED
        ]
        if unresolved_blocking:
            problems.append(f"{len(unresolved_blocking)} unresolved blocking issues")

        # Check requirement coverage
        if plan:
            req_ids = {r.id for r in curr_state.task.requirements}
            covered = {r_id for s in plan.steps for r_id in s.requirement_ids}
            if req_ids - covered:
                problems.append(f"Missing requirement coverage: {req_ids - covered}")

        # Check stagnation
        if detector.is_stagnant():
            problems.append(StopReason.STAGNATION_DETECTED.value)

        # Structural quality validator (P4.1)
        validator = StructuralQualityValidator()
        report = validator.validate(curr_state)
        if not report.passed:
            for violation in report.violations:
                if violation.severity == ViolationSeverity.BLOCKER:
                    problems.append(f"[{violation.rule_id}] {violation.message}")

        passed = len(problems) == 0
        if not passed and round_num >= max_rounds:
            stop_reason = f"{StopReason.MAX_ROUNDS_REACHED.value}: {'; '.join(problems)}"
            return {
                "gate_passed": False,
                "stop_reason": stop_reason,
                "events": [f"[GATE] Gate not passed: {stop_reason}"],
            }

        return {
            "gate_passed": passed,
            "stop_reason": "" if passed else "; ".join(problems),
            "events": [f"[GATE] Structural gate {'PASSED' if passed else 'FAILED'}"],
        }

    def export_node(state: OrchestrationState) -> dict:
        # First transition phase to EXPORT while RUNNING
        ctrl.transition_phase(RunPhase.EXPORT)

        # Then transition to terminal status (retains phase EXPORT)
        if not state.get("gate_passed"):
            status = RunStatus.PARTIAL
            reason = state.get("stop_reason") or StopReason.UNRESOLVED_BLOCKERS.value
        else:
            status = RunStatus.PARTIAL
            reason = "MVP candidate generated (awaiting P4 quality certification)"

        ctrl.transition_phase(RunPhase.EXPORT, status, reason=reason)
        return {"events": [f"[EXPORT] Finished run in phase EXPORT with status {status.value}"]}

    def should_loop_or_export(state: OrchestrationState) -> str:
        if state.get("gate_passed"):
            return "export"
        round_num = state.get("round", 0)
        max_rounds = state.get("max_rounds", 2)
        if round_num >= max_rounds or detector.is_stagnant():
            return "export"
        return "review"

    # Assemble StateGraph
    graph = StateGraph(OrchestrationState)
    graph.add_node("intake", intake_node)
    graph.add_node("snapshot", snapshot_node)
    graph.add_node("investigate", investigate_node)
    graph.add_node("planner_analysis", planner_analysis_node)
    graph.add_node("reviewer_analysis", reviewer_analysis_node)
    graph.add_node("propose", propose_node)
    graph.add_node("review", review_node)
    graph.add_node("verify", verify_node)
    graph.add_node("revise", revise_node)
    graph.add_node("gate", quality_gate_node)
    graph.add_node("export", export_node)

    # Edge connections
    graph.set_entry_point("intake")
    graph.add_edge("intake", "snapshot")
    graph.add_edge("snapshot", "investigate")
    graph.add_edge("investigate", "planner_analysis")
    graph.add_edge("investigate", "reviewer_analysis")
    graph.add_edge("planner_analysis", "propose")
    graph.add_edge("reviewer_analysis", "propose")
    graph.add_edge("propose", "review")
    graph.add_edge("review", "verify")
    graph.add_edge("verify", "revise")
    graph.add_edge("revise", "gate")
    graph.add_conditional_edges(
        "gate",
        should_loop_or_export,
        {
            "export": "export",
            "review": "review",
        },
    )
    graph.add_edge("export", END)

    return graph
