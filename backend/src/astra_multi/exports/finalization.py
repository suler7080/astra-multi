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

from astra_multi.domain.models import (
    RunState,
    RunStatus,
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


@dataclass
class FinalizationDecision:
    target_status: RunStatus
    reason: str
    quality_report: QualityReport
    can_finalize: bool  # True if eligible for RunStatus.FINAL
    pillar_results: dict[str, PillarResult] = field(default_factory=dict)


class FinalizationService:
    """Evaluates whether a candidate plan revision meets the threshold for FINAL certification via the 5-Pillar Gate."""

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
            and v.rule_id not in (STRUCTURAL_RULES | CONTRACT_RULES | GROUNDING_RULES | ISSUE_RULES)
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
            for r in rubrics:
                stat = r.get("status") if isinstance(r, dict) else getattr(r, "status", None)
                rid = r.get("rubric_id") if isinstance(r, dict) else getattr(r, "rubric_id", "R")
                req_id = r.get("req_id") if isinstance(r, dict) else getattr(r, "req_id", "")
                if stat in ("MISSING", "PARTIAL") or (stat is not None and str(stat).upper() != "MET"):
                    missing_or_partial.append(f"Rubric {rid} for '{req_id}' is {stat}")
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

        pillar_results = {
            "structural": pillar_structural,
            "contract_deliverable": pillar_contract,
            "rubric_audit": pillar_rubric,
            "grounding_anti_pattern": pillar_grounding,
            "issue_resolution": pillar_issues,
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

        can_finalize = all(p.passed for p in pillar_results.values())
        if can_finalize:
            return FinalizationDecision(
                target_status=RunStatus.FINAL,
                reason="Candidate plan satisfied all 5-pillar finalization gates (Structural, Contract & Deliverable, Rubric Audit, Grounding, Issue Resolution).",
                quality_report=quality_report,
                can_finalize=True,
                pillar_results=pillar_results,
            )
        else:
            failed_pillars = [p.name for p in pillar_results.values() if not p.passed]
            failed_reasons = [p.details for p in pillar_results.values() if not p.passed]
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=f"5-Pillar finalization check failed [{', '.join(failed_pillars)}]: {'; '.join(failed_reasons)}",
                quality_report=quality_report,
                can_finalize=False,
                pillar_results=pillar_results,
            )


FinalizationEvaluator = FinalizationService
