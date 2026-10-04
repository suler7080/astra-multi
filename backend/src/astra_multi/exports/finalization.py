"""P4.2 Semantic review and finalization service.

Determines the final lifecycle status of a run (FINAL, PARTIAL, WAITING_FOR_INPUT, FAILED, CANCELLED):
- Evaluates structural quality report from P4.1.
- Evaluates semantic criteria (rubric feasibility, correctness, migration/rollback strength).
- Ensures FINAL is ONLY granted when structural validator passes, semantic review passes on current revision,
  and zero open blocking issues / unresolved critical questions remain.
- Stale reviews (reviewed on earlier plan revision) do not qualify for FINAL.
"""

from __future__ import annotations

from dataclasses import dataclass

from astra_multi.domain.models import (
    RunState,
    RunStatus,
)
from astra_multi.exports.quality_validator import (
    QualityReport,
    StructuralQualityValidator,
)


@dataclass
class SemanticReviewAssessment:
    passed: bool
    reviewed_plan_revision: int
    feedback: str
    concerns: list[str]


@dataclass
class FinalizationDecision:
    target_status: RunStatus
    reason: str
    quality_report: QualityReport
    can_finalize: bool  # True if eligible for RunStatus.FINAL


class FinalizationService:
    """Evaluates whether a candidate plan revision meets the threshold for FINAL certification."""

    def __init__(self, validator: StructuralQualityValidator | None = None) -> None:
        self.validator = validator or StructuralQualityValidator()

    def evaluate(
        self,
        state: RunState,
        semantic_review: SemanticReviewAssessment | None = None,
    ) -> FinalizationDecision:
        # 1. Structural evaluation
        quality_report = self.validator.validate(state)

        # If already cancelled or terminated early
        if state.run.status == RunStatus.CANCELLED:
            return FinalizationDecision(
                target_status=RunStatus.CANCELLED,
                reason=state.run.stop_reason or "User cancelled run",
                quality_report=quality_report,
                can_finalize=False,
            )

        # Check for pending blocking questions
        pending_questions = [q for q in state.questions if q.blocking and q.answer is None]
        if pending_questions:
            return FinalizationDecision(
                target_status=RunStatus.WAITING_FOR_INPUT,
                reason=f"Waiting for answer on {len(pending_questions)} blocking question(s)",
                quality_report=quality_report,
                can_finalize=False,
            )

        # If structural gates failed
        if not quality_report.passed:
            blocker_msgs = [v.message for v in quality_report.violations if v.severity.value == "blocker"]
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=f"Structural validation failed: {'; '.join(blocker_msgs)}",
                quality_report=quality_report,
                can_finalize=False,
            )

        # 2. Semantic review checks
        if semantic_review is None:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason="Semantic review assessment not provided",
                quality_report=quality_report,
                can_finalize=False,
            )

        # Check for stale review
        plan_rev = state.plan.revision if state.plan else 0
        if semantic_review.reviewed_plan_revision != plan_rev:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=(
                    f"Semantic review is stale (reviewed revision "
                    f"{semantic_review.reviewed_plan_revision}, current plan revision is {plan_rev})"
                ),
                quality_report=quality_report,
                can_finalize=False,
            )

        if not semantic_review.passed:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=f"Semantic review did not pass: {'; '.join(semantic_review.concerns) or semantic_review.feedback}",
                quality_report=quality_report,
                can_finalize=False,
            )

        # All criteria satisfied: Structural PASS + Semantic PASS on current revision + 0 blockers
        return FinalizationDecision(
            target_status=RunStatus.FINAL,
            reason="Candidate plan satisfied all structural quality gates and semantic review rubrics.",
            quality_report=quality_report,
            can_finalize=True,
        )
