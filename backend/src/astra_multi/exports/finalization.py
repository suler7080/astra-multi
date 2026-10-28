"""P4.2 Semantic review and finalization service.

Determines the final lifecycle status of a run (FINAL, PARTIAL, WAITING_FOR_INPUT, FAILED, CANCELLED):
- Evaluates structural quality report from P4.1.
- Evaluates semantic criteria (rubric feasibility, correctness, migration/rollback strength).
- Ensures FINAL is ONLY granted when structural validator passes, semantic review passes on current revision,
  and zero open blocking issues / unresolved critical questions remain.
- Stale reviews (reviewed on earlier plan revision) do not qualify for FINAL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from astra_multi.domain.evidence import validate_evidence
from astra_multi.domain.models import (
    RunState,
    RunStatus,
    VerdictEvidence,
)
from astra_multi.exports.human_review import (
    evaluate_human_review,
)
from astra_multi.exports.quality_validator import (
    QualityReport,
    StructuralQualityValidator,
    ViolationSeverity,
)


@dataclass
class PillarResult:
    pillar_id: str
    name: str
    passed: bool
    details: str
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class SemanticReviewAssessment:
    passed: bool
    reviewed_plan_revision: int
    feedback: str
    concerns: list[str]
    rubric_audits: list[dict[str, Any]] = field(default_factory=list)
    requirement_verdicts: list[dict[str, Any]] = field(default_factory=list)
    validator_llm_conflicts: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    plan_uncertainty: list[str] = field(default_factory=list)


@dataclass
class FinalizationDecision:
    target_status: RunStatus
    reason: str
    quality_report: QualityReport
    can_finalize: bool  # True if eligible for RunStatus.FINAL
    pillar_results: dict[str, PillarResult] = field(default_factory=dict)


class FinalizationService:
    """Evaluates a candidate plan revision against the 8-Pillar Gate."""

    def __init__(self, validator: StructuralQualityValidator | None = None) -> None:
        self.validator = validator or StructuralQualityValidator()

    def evaluate(
        self,
        state: RunState,
        semantic_review: SemanticReviewAssessment | None = None,
    ) -> FinalizationDecision:
        # Run structural / quality validator
        quality_report = self.validator.validate(state)

        # Categorize violations by rule sets
        STRUCTURAL_RULES = {
            "RULE-STRUCT-001",
            "RULE-UNIQUE-001",
            "RULE-DAG-001",
            "RULE-DAG-002",
            "RULE-DAG-003",
            "RULE-DAG-004",
            "RULE-DAG-005",
            "RULE-DAG-006",
            "RULE-DAG-007",
            "RULE-DAG-008",
        }
        CONTRACT_RULES = {
            "RULE-COV-001",
            "RULE-REF-001",
            "RULE-DESIGN-001",
            "RULE-STEP-001",
            "RULE-STEP-002",
            "RULE-FULFILL-001",
            "RULE-FULFILL-002",
        }
        GROUNDING_RULES = {
            "RULE-TECH-001",
            "RULE-TECH-002",
            "RULE-VAL-001",
        }
        ISSUE_RULES = {
            "RULE-ISSUE-001",
            "RULE-ISSUE-002",
        }
        OWNERSHIP_RULES = {
            "RULE-ASSIGN-001",
            "RULE-ASSIGN-002",
            "RULE-ASSIGN-003",
            "RULE-ASSIGN-004",
            "RULE-ASSIGN-005",
            "RULE-ASSIGN-007",
            "RULE-ASSIGN-008",
            "RULE-ASSIGN-009",
            "RULE-ASSIGN-010",
            "RULE-ASSIGN-012",
        }
        RUNTIME_RULES = {
            "RULE-RUNTIME-001",
            "RULE-RUNTIME-002",
            "RULE-RUNTIME-003",
            "RULE-DIFF-001",
            "RULE-DIFF-002",
        }

        # 1. Structural Gate
        struct_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in STRUCTURAL_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        has_steps = bool(state.plan and state.plan.steps)
        if not has_steps and not struct_blockers:
            struct_blockers.append("Candidate plan has no execution steps.")
        other_blockers = [
            v.message for v in quality_report.violations
            if v.severity == ViolationSeverity.BLOCKER
            and v.rule_id
            not in (
                STRUCTURAL_RULES
                | CONTRACT_RULES
                | GROUNDING_RULES
                | ISSUE_RULES
                | OWNERSHIP_RULES
                | RUNTIME_RULES
            )
        ]
        if other_blockers:
            struct_blockers.extend(other_blockers)

        struct_passed = len(struct_blockers) == 0 and has_steps
        pillar_structural = PillarResult(
            pillar_id="structural",
            name="Structural Gate",
            passed=struct_passed,
            details="Connected DAG graph with depth >= 2 and zero isolated steps." if struct_passed else f"Structural validation failed: {'; '.join(struct_blockers)}",
            diagnostics=struct_blockers,
        )

        # 2. Contract & Deliverable Gate
        contract_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in CONTRACT_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        if quality_report.uncovered_requirements:
            msg = f"Uncovered requirements: {', '.join(quality_report.uncovered_requirements)}"
            if msg not in contract_blockers:
                contract_blockers.append(msg)
        contract_passed = len(contract_blockers) == 0
        pillar_contract = PillarResult(
            pillar_id="contract_deliverable",
            name="Contract & Deliverable Gate",
            passed=contract_passed,
            details="100% of requirements fulfilled with concrete deliverables matching expected artifact types." if contract_passed else f"Contract & deliverable validation failed: {'; '.join(contract_blockers)}",
            diagnostics=contract_blockers,
        )

        # 3. Rubric Audit Gate
        rubric_diagnostics: list[str] = []
        plan_rev = state.plan.revision if state.plan else 0
        if semantic_review is None:
            rubric_passed = False
            rubric_details = "Semantic review assessment not provided"
            rubric_diagnostics.append(rubric_details)
        elif semantic_review.reviewed_plan_revision != plan_rev:
            rubric_passed = False
            rubric_details = (
                f"Semantic review is stale (reviewed revision "
                f"{semantic_review.reviewed_plan_revision}, current plan revision is {plan_rev})"
            )
            rubric_diagnostics.append(rubric_details)
        elif not semantic_review.passed:
            rubric_passed = False
            rubric_details = f"Semantic review did not pass: {'; '.join(semantic_review.concerns) or semantic_review.feedback}"
            rubric_diagnostics.extend(semantic_review.concerns or [semantic_review.feedback])
        else:
            rubrics = getattr(semantic_review, "rubric_audits", []) or []
            missing_or_partial: list[str] = []
            plan = state.plan
            for r in rubrics:
                stat = r.get("status") if isinstance(r, dict) else getattr(r, "status", None)
                rid = r.get("rubric_id") if isinstance(r, dict) else getattr(r, "rubric_id", "R")
                raw_req_id = (
                    r.get("req_id")
                    if isinstance(r, dict)
                    else getattr(r, "req_id", "")
                )
                req_id = str(raw_req_id) if raw_req_id is not None else ""
                evidence = r.get("evidence") if isinstance(r, dict) else getattr(r, "evidence", None)
                if stat in ("MISSING", "PARTIAL") or (stat is not None and str(stat).upper() != "MET"):
                    missing_or_partial.append(f"Rubric {rid} for '{req_id}' is {stat}")
                elif not evidence:
                    missing_or_partial.append(
                        f"Rubric {rid} for '{req_id}' is MET without evidence"
                    )
                elif plan is None:
                    missing_or_partial.append(
                        f"Rubric {rid} for '{req_id}' has evidence but no plan revision"
                    )
                else:
                    problems: list[str] = []
                    valid_evidence = 0
                    for item in evidence:
                        try:
                            parsed = (
                                item
                                if isinstance(item, VerdictEvidence)
                                else VerdictEvidence.model_validate(item)
                            )
                        except ValidationError:
                            problems.append("evidence payload is invalid")
                            continue
                        problem = validate_evidence(
                            parsed, requirement_id=req_id, plan=plan
                        )
                        if problem is None:
                            valid_evidence += 1
                        else:
                            problems.append(problem)
                    if valid_evidence == 0:
                        detail = "; ".join(problems) or "no evidence attached"
                        missing_or_partial.append(
                            f"Rubric {rid} for '{req_id}' is MET without valid "
                            f"deterministic evidence: {detail}"
                        )
            if missing_or_partial:
                rubric_passed = False
                rubric_details = f"Rubric audit failed: {'; '.join(missing_or_partial)}"
                rubric_diagnostics.extend(missing_or_partial)
            else:
                rubric_passed = True
                rubric_details = "Reviewer rubric audit passed with 100% MET (0 MISSING, 0 PARTIAL)."
        pillar_rubric = PillarResult(
            pillar_id="rubric_audit",
            name="Rubric Audit Gate",
            passed=rubric_passed,
            details=rubric_details,
            diagnostics=rubric_diagnostics,
        )

        # 4. Grounding & Anti-Pattern Gate
        grounding_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in GROUNDING_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        grounding_passed = len(grounding_blockers) == 0
        pillar_grounding = PillarResult(
            pillar_id="grounding_anti_pattern",
            name="Grounding & Anti-Pattern Gate",
            passed=grounding_passed,
            details="Zero physical constraint violations and zero unaddressed sandbox verification failures." if grounding_passed else f"Grounding & anti-pattern gate failed: {'; '.join(grounding_blockers)}",
            diagnostics=grounding_blockers,
        )

        # 5. Issue Resolution Gate
        issue_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in ISSUE_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        if quality_report.unresolved_blocking_issues:
            for unres in quality_report.unresolved_blocking_issues:
                msg = f"Blocking issue remains unresolved: {unres}"
                if msg not in issue_blockers:
                    issue_blockers.append(msg)
        issue_passed = len(issue_blockers) == 0
        pillar_issues = PillarResult(
            pillar_id="issue_resolution",
            name="Issue Resolution Gate",
            passed=issue_passed,
            details="Zero open blocking or warning issues remain unresolved." if issue_passed else f"Issue resolution gate failed: {'; '.join(issue_blockers)}",
            diagnostics=issue_blockers,
        )

        # 6. Ownership Contract Gate (structured assignment matrix)
        ownership_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in OWNERSHIP_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        ownership_passed = len(ownership_blockers) == 0
        pillar_ownership = PillarResult(
            pillar_id="ownership_contract",
            name="Ownership Contract Gate",
            passed=ownership_passed,
            details=(
                "Every requirement, step and target file has exactly one owner."
                if ownership_passed
                else f"Ownership contract validation failed: {'; '.join(ownership_blockers)}"
            ),
            diagnostics=ownership_blockers,
        )

        # 7. Runtime Scope & Diff Gate
        runtime_blockers = [
            v.message for v in quality_report.violations
            if v.rule_id in RUNTIME_RULES and v.severity == ViolationSeverity.BLOCKER
        ]
        runtime_passed = len(runtime_blockers) == 0
        pillar_runtime = PillarResult(
            pillar_id="runtime_scope",
            name="Runtime Scope & Diff Gate",
            passed=runtime_passed,
            details=(
                "All recorded worker executions stayed inside their leased scope."
                if runtime_passed
                else f"Runtime scope/diff validation failed: {'; '.join(runtime_blockers)}"
            ),
            diagnostics=runtime_blockers,
        )

        # 8. Risk-Based Human Review Gate
        human_review = evaluate_human_review(state, quality_report, semantic_review)
        human_passed = not human_review.required
        if human_review.required:
            human_details = (
                "Human review required before FINAL: "
                + "; ".join(trigger.message for trigger in human_review.triggers)
            )
        elif human_review.triggers and human_review.approved:
            human_details = (
                "Human review triggers acknowledged by an approval for plan "
                f"revision {human_review.plan_revision}."
            )
        else:
            human_details = "No risk-based human review trigger detected."
        pillar_human = PillarResult(
            pillar_id="human_review",
            name="Human Review Gate",
            passed=human_passed,
            details=human_details,
            diagnostics=[t.message for t in human_review.triggers],
        )

        pillar_results = {
            "structural": pillar_structural,
            "contract_deliverable": pillar_contract,
            "ownership_contract": pillar_ownership,
            "rubric_audit": pillar_rubric,
            "grounding_anti_pattern": pillar_grounding,
            "issue_resolution": pillar_issues,
            "runtime_scope": pillar_runtime,
            "human_review": pillar_human,
        }

        # If already cancelled or terminated early
        if state.run.status == RunStatus.CANCELLED:
            return FinalizationDecision(
                target_status=RunStatus.CANCELLED,
                reason=state.run.stop_reason or "User cancelled run",
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )

        # Check for pending blocking questions
        pending_questions = [q for q in state.questions if q.blocking and q.answer is None]
        if pending_questions:
            return FinalizationDecision(
                target_status=RunStatus.WAITING_FOR_INPUT,
                reason=f"Waiting for answer on {len(pending_questions)} blocking question(s)",
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )

        # A risk trigger pauses the run for an explicit human decision, even when
        # some gates also failed: the human needs to see the whole picture.
        if human_review.required:
            failed = [p.name for p in pillar_results.values() if not p.passed]
            return FinalizationDecision(
                target_status=RunStatus.WAITING_FOR_HUMAN_REVIEW,
                reason=(
                    "8-Pillar finalization requires human review "
                    f"[{', '.join(failed)}]: {human_details}"
                ),
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )

        hard_pillars = (
            "structural",
            "contract_deliverable",
            "ownership_contract",
            "rubric_audit",
            "grounding_anti_pattern",
            "issue_resolution",
        )
        hard_failures = [
            pillar_results[key]
            for key in hard_pillars
            if not pillar_results[key].passed
        ]
        if hard_failures:
            failed_pillars = [p.name for p in hard_failures]
            failed_reasons = [p.details for p in hard_failures]
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=(
                    f"8-Pillar finalization check failed "
                    f"[{', '.join(failed_pillars)}]: {'; '.join(failed_reasons)}"
                ),
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )

        if not pillar_runtime.passed:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=(
                    "8-Pillar finalization check failed "
                    f"[{pillar_runtime.name}]: {pillar_runtime.details}"
                ),
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )

        return FinalizationDecision(
            target_status=RunStatus.FINAL,
            reason=(
                "Candidate plan satisfied all 8 finalization gates (Structural, "
                "Contract & Deliverable, Ownership, Rubric Audit, Grounding, "
                "Issue Resolution, Runtime Scope, Human Review)."
            ),
            quality_report=quality_report,
            can_finalize=True,
            pillar_results=pillar_results,
        )


FinalizationEvaluator = FinalizationService
