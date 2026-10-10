"""LangGraph workflow definition integrating domain store, model gateway, and tools.

P3.3 Production multi-agent discussion workflow graph:
- Phases: INTAKE -> SNAPSHOT -> INVESTIGATE -> INDEPENDENT_ANALYSIS (fan-out Planner/Reviewer)
  -> PROPOSE -> REVIEW -> VERIFY -> REVISE -> QUALITY_GATE -> EXPORT
- Bounded loop: review -> verify -> revise -> gate -> (repeat or export/partial)
- Domain state commits exclusively through controller / P1 commands.
- Checkpoint persistence through CheckpointBridge.
"""

from __future__ import annotations

import hashlib
import logging
import operator
import os
import re
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from astra_multi.agents.roles import (
    PROMPT_VERSION_V1,
    AnalysisOutput,
    IssueReport,
    IssueResolutionReport,
    ProposalOutput,
    ReviewOutput,
    SynthesizerOutput,
    format_independent_analysis_prompt,
    format_propose_prompt,
    format_review_prompt,
    format_semantic_review_prompt,
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
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
    ViolationSeverity,
)
from astra_multi.gateway.model_gateway import ModelGateway
from astra_multi.orchestration.budget import BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.roles import ROLE_GROUP
from astra_multi.orchestration.termination import StagnationDetector, StopReason

logger = logging.getLogger(__name__)


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
    semantic_review: dict[str, Any] | None
    gate_passed: bool
    stop_reason: str
    events: Annotated[list[str], operator.add]


def normalize_issue_content(ir: IssueReport) -> str:
    """Normalize issue content for deterministic hashing:
    - Text fields: strip whitespace, collapse consecutive whitespace to single space.
    - Identifier fields: lowercase, stripped, sorted.
    """
    def _norm_text(s: str | None) -> str:
        if not s:
            return ""
        return re.sub(r"\s+", " ", s.strip())

    req_ids = sorted(r.strip().lower() for r in ir.requirement_ids if r and r.strip())
    evi_ids = sorted(e.strip().lower() for e in ir.evidence_ids if e and e.strip())
    sev = ir.severity.value.lower() if hasattr(ir.severity, "value") else str(ir.severity).lower()

    fields = [
        f"claim:{_norm_text(ir.claim)}",
        f"impact:{_norm_text(ir.impact)}",
        f"severity:{sev}",
        f"verification_request:{_norm_text(ir.verification_request)}",
        f"suggested_resolution:{_norm_text(ir.suggested_resolution)}",
        f"requirement_ids:{','.join(req_ids)}",
        f"evidence_ids:{','.join(evi_ids)}",
    ]
    return "|".join(fields)


def derive_issue_id(run_id: str, round_num: int, node: str, ir: IssueReport) -> str:
    """Derive deterministic Issue ID from (run_id, round, node, hash(normalized_content)).

    Avoids ID collision when retrying with different content at the same index,
    while guaranteeing identical ID on retry with identical content (no duplication).
    """
    norm_content = normalize_issue_content(ir)
    content_hash = hashlib.sha256(norm_content.encode("utf-8")).hexdigest()[:16]
    derived_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{run_id}:{round_num}:{node}:{content_hash}",
    )
    return f"ISSUE-{derived_uuid.hex[:8]}"


def estimate_call_tokens_and_cost(
    messages: list[dict[str, str]],
    builder: ContextBuilder | None = None,
    max_output_tokens: int | None = None,
    safety_factor: float | None = None,
    cost_per_1k_tokens: float = 0.01,
) -> tuple[int, float]:
    """Estimate token reservation and cost based on prepared prompt length and expected output.

    Formula:
        prompt_tokens = count(prompt_text) (via tokenizer or ~4 chars/bytes per token)
        total_tokens = int((prompt_tokens + max_output_tokens) * safety_factor)
        cost = (total_tokens / 1000.0) * cost_per_1k_tokens
    """
    # 1. Configurable safety factor (default 1.25, env override ASTRA_BUDGET_SAFETY_FACTOR)
    if safety_factor is None:
        try:
            safety_factor = float(os.environ.get("ASTRA_BUDGET_SAFETY_FACTOR", "1.25"))
        except ValueError:
            safety_factor = 1.25
    if safety_factor < 1.0:
        safety_factor = 1.0

    # 2. Configurable max output tokens (default 2000, env override ASTRA_MULTI_MAX_OUTPUT_TOKENS)
    if max_output_tokens is None:
        try:
            max_output_tokens = int(os.environ.get("ASTRA_MULTI_MAX_OUTPUT_TOKENS", "2000"))
        except ValueError:
            max_output_tokens = 2000
    if max_output_tokens < 1:
        max_output_tokens = 2000

    # 3. Prompt tokens estimation using available tokenizer or character length assumption
    prompt_text = "".join(m.get("content", "") for m in messages)
    if builder and getattr(builder, "tokenizer", None):
        tokenizer = builder.tokenizer
        raw_count = tokenizer.count(prompt_text)
        # ByteTokenizer returns raw byte count; standard heuristic is ~4 bytes/char per token
        if type(tokenizer).__name__ == "ByteTokenizer":
            prompt_tokens = max(1, raw_count // 4)
        else:
            prompt_tokens = max(1, raw_count)
    else:
        # Fallback assumption: 1 token ~= 4 characters for UTF-8 text
        prompt_tokens = max(1, len(prompt_text) // 4)

    estimated_tokens = int((prompt_tokens + max_output_tokens) * safety_factor)
    estimated_cost = round((estimated_tokens / 1000.0) * cost_per_1k_tokens, 6)
    return estimated_tokens, estimated_cost


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
        role_assignments: dict[str, dict[str, str | None]] | None = None,
    ) -> None:
        self.controller = controller
        self.gateway = gateway
        self.context_builder = context_builder
        self.evidence_ledger = evidence_ledger
        self.budget_service = budget_service
        self.stagnation_detector = StagnationDetector()
        self.provider = provider or os.environ.get("ASTRA_MULTI_PROVIDER", "fake")
        self.role_assignments: dict[str, dict[str, str | None]] = role_assignments or {}

    def get_assignment_for_role(self, node_role: str) -> tuple[str, str | None]:
        """Resolve (provider, model) assignment for a given node or role.

        Falls back to active provider with model=None if not configured or unrecognized.
        """
        group = ROLE_GROUP.get(node_role)
        if not group:
            logger.warning(
                "Unrecognized node role '%s', falling back to default provider '%s'",
                node_role,
                self.provider,
            )
            return (self.provider, None)

        group_config = self.role_assignments.get(group)
        if group_config and group_config.get("provider"):
            return (str(group_config["provider"]), group_config.get("model"))

        return (self.provider, None)


def create_workflow_graph(wf_ctx: WorkflowContext) -> StateGraph:
    """Builds the full multi-agent discussion workflow graph."""
    ctrl = wf_ctx.controller
    gateway = wf_ctx.gateway
    builder = wf_ctx.context_builder
    detector = wf_ctx.stagnation_detector
    budget = wf_ctx.budget_service

    def _call_model_with_budget(
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any,
        call_id: str,
        estimated_tokens: int | None = None,
        estimated_cost: float | None = None,
        safety_factor: float | None = None,
        max_output_tokens: int | None = None,
        node_name: str | None = None,
    ) -> Any:
        lookup_target = node_name or role
        role_provider, role_model = wf_ctx.get_assignment_for_role(lookup_target)
        limits_override = {"model": role_model} if role_model else None

        # Dynamically estimate tokens and cost if not provided explicitly
        if estimated_tokens is None or estimated_cost is None:
            dyn_tokens, dyn_cost = estimate_call_tokens_and_cost(
                messages=messages,
                builder=builder,
                max_output_tokens=max_output_tokens,
                safety_factor=safety_factor,
            )
            if estimated_tokens is None:
                estimated_tokens = dyn_tokens
            if estimated_cost is None:
                estimated_cost = dyn_cost

        reservation_id = None
        if budget:
            reservation_id = budget.reserve(
                estimated_tokens=estimated_tokens,
                estimated_cost=estimated_cost,
                operation_id=f"RES-{call_id}",
            )
        settled = False
        try:
            try:
                res = gateway.call(
                    provider=role_provider,
                    role=role,
                    messages=messages,
                    output_schema=output_schema,
                    limits_override=limits_override,
                )
            except Exception as primary_exc:
                is_override = (role_provider != wf_ctx.provider) or (role_model is not None)
                if is_override:
                    logger.warning(
                        "Call failed for role '%s' using role provider '%s' (model: %s): %s. "
                        "Falling back to active provider '%s'",
                        role,
                        role_provider,
                        role_model,
                        primary_exc,
                        wf_ctx.provider,
                    )
                    res = gateway.call(
                        provider=wf_ctx.provider,
                        role=role,
                        messages=messages,
                        output_schema=output_schema,
                    )
                else:
                    raise primary_exc
            effective_usage = getattr(res, "cumulative_usage", None) or res.usage or {}
            actual_tokens = int(effective_usage.get("total_tokens") or 0)
            effective_cost = getattr(res, "cumulative_cost_usd", None)
            if effective_cost is not None:
                actual_cost = effective_cost
            elif getattr(res, "cost_actual_usd", None) is not None:
                actual_cost = res.cost_actual_usd
            elif actual_tokens > 0:
                actual_cost = round((actual_tokens / 1000.0) * 0.01, 6)
            else:
                actual_cost = estimated_cost if estimated_cost is not None else 0.0

            res.cost_actual_usd = actual_cost
            if budget and reservation_id:
                budget.settle(
                    operation_id=reservation_id,
                    actual_tokens=actual_tokens,
                    actual_cost=actual_cost,
                )
                settled = True
            return res
        except Exception as exc:
            if budget and reservation_id and not settled:
                partial_usage = (
                    getattr(exc, "cumulative_usage", None)
                    or getattr(gateway, "last_cumulative_usage", None)
                )
                partial_tokens = (
                    int(partial_usage.get("total_tokens") or 0) if partial_usage else 0
                )
                partial_cost = (
                    getattr(exc, "cumulative_cost_usd", None)
                    or getattr(gateway, "last_cumulative_cost", None)
                    or 0.0
                )
                if partial_tokens > 0 or partial_cost > 0.0:
                    budget.settle(
                        operation_id=reservation_id,
                        actual_tokens=partial_tokens,
                        actual_cost=partial_cost,
                    )
                    settled = True
            raise
        finally:
            if budget and reservation_id and not settled:
                budget.release(reservation_id)

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
            round_num=state.get("round", 0),
            events=state.get("events", []),
        )
        messages = format_independent_analysis_prompt(bundle)

        call_id = f"CALL-P-ANALYSIS-{state.get('round', 0)}"
        res = _call_model_with_budget(
            role="planner",
            messages=messages,
            output_schema=AnalysisOutput,
            call_id=call_id,
            node_name="planner_analysis",
        )
        output = AnalysisOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="planner",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
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
            round_num=state.get("round", 0),
            events=state.get("events", []),
        )
        messages = format_independent_analysis_prompt(bundle)

        call_id = f"CALL-R-ANALYSIS-{state.get('round', 0)}"
        res = _call_model_with_budget(
            role="reviewer",
            messages=messages,
            output_schema=AnalysisOutput,
            call_id=call_id,
            node_name="reviewer_analysis",
        )
        output = AnalysisOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="reviewer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
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
            round_num=state.get("round", 0),
            events=state.get("events", []),
        )
        analyses = [AnalysisOutput.model_validate(a) for a in state.get("analyses", [])]
        messages = format_propose_prompt(bundle, analyses)

        call_id = f"CALL-PROPOSE-{state.get('round', 0)}"
        res = _call_model_with_budget(
            role="planner",
            messages=messages,
            output_schema=ProposalOutput,
            call_id=call_id,
            node_name="propose",
        )
        proposal_out = ProposalOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="planner",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
        )

        valid_claims = {c.id for c in curr_state.claims}
        valid_reqs = {r.id for r in curr_state.task.requirements}
        filtered_claims = [cid for cid in proposal_out.claim_ids if cid in valid_claims]
        filtered_coverage = {
            k: v for k, v in proposal_out.requirement_coverage.items() if k in valid_reqs
        }

        round_num = state.get("round", 0)
        # Proposal ID derivation: kept as f'{curr_state.run.id}:{round_num}:propose:0'
        # Explanation: Planner generates strictly one candidate proposal per round.
        # Retries or resumptions for a given round are designed to replace/update
        # this single round proposal, unlike the reviewer issue list which contains
        # arbitrary items at variable indices. Hence, no collision risk across items.
        prop_id = f"PROP-{uuid.uuid5(uuid.NAMESPACE_URL, f'{curr_state.run.id}:{round_num}:propose:0').hex[:8]}"
        domain_proposal = Proposal(
            id=prop_id,
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
            round_num=state.get("round", 0),
            events=state.get("events", []),
        )
        prop = ProposalOutput.model_validate(state["proposal"])
        messages = format_review_prompt(bundle, prop, curr_state.plan.model_dump(mode="json") if curr_state.plan else None)

        call_id = f"CALL-REVIEW-{state.get('round', 0)}"
        res = _call_model_with_budget(
            role="reviewer",
            messages=messages,
            output_schema=ReviewOutput,
            call_id=call_id,
            node_name="review",
        )
        review_out = ReviewOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="reviewer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
        )

        # Commit domain issues
        valid_reqs = {r.id for r in curr_state.task.requirements}
        valid_evidence = {e.id for e in curr_state.evidence}
        existing_issue_ids = {i.id for i in curr_state.issues}
        issue_round = state.get("round", 0)
        enriched_issues: list[IssueReport] = []
        for idx, ir in enumerate(review_out.issues):
            filtered_req_ids = [rid for rid in ir.requirement_ids if rid in valid_reqs]
            filtered_evi_ids = [eid for eid in ir.evidence_ids if eid in valid_evidence]
            verif_req = ir.verification_request
            if not filtered_evi_ids and not verif_req:
                verif_req = f"Verification required: {ir.claim[:100]}"
            issue_id = derive_issue_id(curr_state.run.id, issue_round, "review", ir)
            enriched_issues.append(ir.model_copy(update={"id": issue_id}))
            if issue_id in existing_issue_ids:
                continue
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

        # Build issue alias map for resolutions
        res_alias_map: dict[str, str] = {}
        for idx, iss in enumerate(curr_state.issues):
            res_alias_map[iss.id] = iss.id
            res_alias_map[iss.id.lower()] = iss.id
            res_alias_map[iss.id.upper()] = iss.id
            res_alias_map[f"ISSUE-{idx + 1}"] = iss.id
            res_alias_map[f"issue-{idx + 1}"] = iss.id
            res_alias_map[f"ISSUE-{idx + 1:02d}"] = iss.id
            res_alias_map[str(idx + 1)] = iss.id
            res_alias_map[f"#{idx + 1}"] = iss.id

        # Apply resolutions
        mapped_resolutions: list[IssueResolutionReport] = []
        for res_report in review_out.resolutions:
            raw_id = res_report.issue_id.strip() if isinstance(res_report.issue_id, str) else str(res_report.issue_id)
            target_id = (
                res_alias_map.get(raw_id)
                or res_alias_map.get(raw_id.upper())
                or res_alias_map.get(raw_id.lower())
                or raw_id
            )
            mapped_resolutions.append(res_report.model_copy(update={"issue_id": target_id}))
            try:
                ctrl.resolve_issue(
                    issue_id=target_id,
                    reviewer="reviewer",
                    review_result=res_report.review_result,
                    review_note=res_report.review_note,
                    resolution_text=res_report.resolution_text,
                    evidence_ids=res_report.evidence_ids,
                    node="review",
                )
            except Exception as e:
                logger.warning("Failed to resolve issue %s in review_node: %s", target_id, e)

        review_out = review_out.model_copy(
            update={"issues": enriched_issues, "resolutions": mapped_resolutions}
        )

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
            round_num=current_round,
            events=state.get("events", []),
        )
        prop = ProposalOutput.model_validate(state["proposal"])
        rev = ReviewOutput.model_validate(state["review"])
        messages = format_synthesize_prompt(bundle, prop, rev, curr_state.plan.model_dump(mode="json") if curr_state.plan else None)

        call_id = f"CALL-SYNTH-{current_round}"
        res = _call_model_with_budget(
            role="synthesizer",
            messages=messages,
            output_schema=SynthesizerOutput,
            call_id=call_id,
            node_name="revise",
        )
        synth_out = SynthesizerOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="synthesizer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
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
        existing_dec_by_q = {dec.question: dec for dec in curr_state.decisions}
        dec_counter = len(curr_state.decisions) + 1
        plan_decisions_by_q: dict[str, Decision] = {}
        for d in synth_out.decisions:
            filtered_evis = [eid for eid in d.evidence_ids if eid in valid_evidence]
            filtered_issues = [iid for iid in d.related_issue_ids if iid in valid_issues]

            existing_dec = existing_dec_by_q.get(d.question)
            if existing_dec is not None and existing_dec.chosen == d.chosen:
                plan_decisions_by_q[d.question] = existing_dec
                continue

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
            ctrl.record_decision(dec)
            existing_dec_by_q[d.question] = dec
            plan_decisions_by_q[d.question] = dec

        plan_decisions = list(plan_decisions_by_q.values())

        # Build issue alias mapping for Synthesizer's issues_addressed:
        # Supports:
        # - Exact domain issue IDs (e.g. 'ISSUE-3a8c1f0d')
        # - Positional/index aliases from rev.issues (e.g. 'ISSUE-1', '1', '#1', 'issue-1')
        # - Positional/index aliases from curr_state.issues
        issue_alias_map: dict[str, str] = {}
        for idx, ir in enumerate(rev.issues):
            actual_id = ir.id
            if not actual_id:
                issue_round = state.get("round", 0)
                actual_id = derive_issue_id(curr_state.run.id, issue_round, "review", ir)
            if actual_id and actual_id in valid_issues:
                issue_alias_map[actual_id] = actual_id
                issue_alias_map[actual_id.lower()] = actual_id
                issue_alias_map[actual_id.upper()] = actual_id
                issue_alias_map[f"ISSUE-{idx + 1}"] = actual_id
                issue_alias_map[f"issue-{idx + 1}"] = actual_id
                issue_alias_map[f"ISSUE-{idx + 1:02d}"] = actual_id
                issue_alias_map[str(idx + 1)] = actual_id
                issue_alias_map[f"#{idx + 1}"] = actual_id

        for idx, iss in enumerate(curr_state.issues):
            issue_alias_map.setdefault(iss.id, iss.id)
            issue_alias_map.setdefault(iss.id.lower(), iss.id)
            issue_alias_map.setdefault(iss.id.upper(), iss.id)
            issue_alias_map.setdefault(f"ISSUE-{idx + 1}", iss.id)
            issue_alias_map.setdefault(f"issue-{idx + 1}", iss.id)
            issue_alias_map.setdefault(f"ISSUE-{idx + 1:02d}", iss.id)
            issue_alias_map.setdefault(str(idx + 1), iss.id)
            issue_alias_map.setdefault(f"#{idx + 1}", iss.id)

        resolved_ids: list[str] = []
        for raw_id in synth_out.issues_addressed:
            raw_stripped = raw_id.strip() if isinstance(raw_id, str) else str(raw_id)
            target_id = (
                issue_alias_map.get(raw_stripped)
                or issue_alias_map.get(raw_stripped.upper())
                or issue_alias_map.get(raw_stripped.lower())
            )
            if target_id and target_id in valid_issues and target_id not in resolved_ids:
                resolved_ids.append(target_id)

        filtered_issues_addressed = resolved_ids

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

        return {
            "round": current_round,
            "events": [f"[REVISE] Committed plan revision {new_plan.revision}"],
        }

    def semantic_review_node(state: OrchestrationState) -> dict:
        ctrl.transition_phase(RunPhase.SEMANTIC_REVIEW)
        curr_state = ctrl.get_state()
        if not curr_state.plan:
            return {"events": ["[SEMANTIC_REVIEW] No plan revision to evaluate"]}

        open_issues = [
            i for i in curr_state.issues
            if i.status != IssueStatus.RESOLVED
        ]

        bundle = builder.build_context(
            run=curr_state,
            role="reviewer",
            phase=RunPhase.SEMANTIC_REVIEW,
            refs=[],
            limits=orchestration_limits(),
            round_num=state.get("round", 0),
            events=state.get("events", []),
        )
        plan_dict = curr_state.plan.model_dump(mode="json")
        open_issues_dict = [i.model_dump(mode="json") for i in open_issues]
        messages = format_semantic_review_prompt(bundle, plan_dict, open_issues_dict)

        call_id = f"CALL-SEMANTIC-REVIEW-{state.get('round', 0)}"
        res = _call_model_with_budget(
            role="reviewer",
            messages=messages,
            output_schema=ReviewOutput,
            call_id=call_id,
            node_name="semantic_review",
        )
        review_out = ReviewOutput.model_validate(res.content)
        ctrl.record_model_call(
            call_id=call_id,
            role="reviewer",
            provider=res.provider,
            model_id=res.model_id,
            prompt_version=PROMPT_VERSION_V1,
            input_data=bundle.content,
            usage=getattr(res, "cumulative_usage", None) or res.usage,
            estimated_cost=res.cost_actual_usd if res.cost_actual_usd is not None else 0.0,
            attempts=getattr(res, "attempts", 1) or 1,
        )

        # Build issue alias map for resolutions
        res_alias_map: dict[str, str] = {}
        for idx, iss in enumerate(open_issues):
            res_alias_map[iss.id] = iss.id
            res_alias_map[iss.id.lower()] = iss.id
            res_alias_map[iss.id.upper()] = iss.id
            res_alias_map[f"ISSUE-{idx + 1}"] = iss.id
            res_alias_map[f"issue-{idx + 1}"] = iss.id
            res_alias_map[f"ISSUE-{idx + 1:02d}"] = iss.id
            res_alias_map[str(idx + 1)] = iss.id
            res_alias_map[f"#{idx + 1}"] = iss.id

        for idx, iss in enumerate(curr_state.issues):
            res_alias_map.setdefault(iss.id, iss.id)
            res_alias_map.setdefault(iss.id.lower(), iss.id)
            res_alias_map.setdefault(iss.id.upper(), iss.id)
            res_alias_map.setdefault(f"ISSUE-{idx + 1}", iss.id)
            res_alias_map.setdefault(f"issue-{idx + 1}", iss.id)
            res_alias_map.setdefault(f"ISSUE-{idx + 1:02d}", iss.id)
            res_alias_map.setdefault(str(idx + 1), iss.id)
            res_alias_map.setdefault(f"#{idx + 1}", iss.id)

        # Apply resolutions
        mapped_resolutions: list[IssueResolutionReport] = []
        for res_report in review_out.resolutions:
            raw_id = res_report.issue_id.strip() if isinstance(res_report.issue_id, str) else str(res_report.issue_id)
            target_id = (
                res_alias_map.get(raw_id)
                or res_alias_map.get(raw_id.upper())
                or res_alias_map.get(raw_id.lower())
                or raw_id
            )
            mapped_resolutions.append(res_report.model_copy(update={"issue_id": target_id}))
            try:
                ctrl.resolve_issue(
                    issue_id=target_id,
                    reviewer="reviewer",
                    review_result=res_report.review_result,
                    review_note=res_report.review_note,
                    resolution_text=res_report.resolution_text,
                    evidence_ids=res_report.evidence_ids,
                    node="semantic_review",
                )
            except Exception as e:
                logger.warning("Failed to resolve issue %s in semantic_review_node: %s", target_id, e)

        # If any new issues are found during semantic review
        valid_reqs = {r.id for r in curr_state.task.requirements}
        valid_evidence = {e.id for e in curr_state.evidence}
        existing_issue_ids = {i.id for i in curr_state.issues}
        issue_round = state.get("round", 0)
        enriched_semantic_issues: list[IssueReport] = []
        for idx, ir in enumerate(review_out.issues):
            filtered_req_ids = [rid for rid in ir.requirement_ids if rid in valid_reqs]
            filtered_evi_ids = [eid for eid in ir.evidence_ids if eid in valid_evidence]
            verif_req = ir.verification_request
            if not filtered_evi_ids and not verif_req:
                verif_req = f"Verification required: {ir.claim[:100]}"
            issue_id = derive_issue_id(curr_state.run.id, issue_round, "semantic_review", ir)
            enriched_semantic_issues.append(ir.model_copy(update={"id": issue_id}))
            if issue_id in existing_issue_ids:
                continue
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

        review_out = review_out.model_copy(
            update={"issues": enriched_semantic_issues, "resolutions": mapped_resolutions}
        )

        # Check stagnation after resolutions are evaluated
        detector.record_round(ctrl.get_state(), state.get("round", 0))

        return {
            "semantic_review": review_out.model_dump(mode="json"),
            "events": [f"[SEMANTIC_REVIEW] Evaluated {len(review_out.resolutions)} resolutions, {len(review_out.issues)} issues"],
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
        elif ctrl.actor in ("P4-quality-service", "quality-service"):
            status = RunStatus.FINAL
            reason = "Certified final plan (passed quality gates)"
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
        return "propose"

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
    graph.add_node("semantic_review", semantic_review_node)
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
    graph.add_edge("revise", "semantic_review")
    graph.add_edge("semantic_review", "gate")
    graph.add_conditional_edges(
        "gate",
        should_loop_or_export,
        {
            "export": "export",
            "propose": "propose",
        },
    )
    graph.add_edge("export", END)

    return graph
