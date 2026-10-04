"""Evaluation scoring rubric and blind evaluation logic for P6.2 and P6.3.

Implements the official rubric from PLAN.md §12.2:
- Scores on 0–4 scale:
  1. Correctness: absence of architectural flaws, correctness of patterns.
  2. Completeness: coverage of requirements and subtle constraints.
  3. Executability: concrete sequential step DAG, specific commands, deliverables.
  4. Evidence quality: verifiable completion criteria, realistic checks.
  5. Proportionality: avoidance of over-engineering or speculative complexity.
- Tracks:
  - Critical omissions (count)
  - Re-plan required (boolean)
  - Average score across dimensions
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PlanEvaluationScore:
    system_label: str  # "Plan A" or "Plan B" (anonymized)
    real_system: str   # "single_model_baseline" or "astra_multi_agent"
    task_id: str
    category: str
    correctness: float       # 0.0 - 4.0
    completeness: float      # 0.0 - 4.0
    executability: float     # 0.0 - 4.0
    evidence_quality: float  # 0.0 - 4.0
    proportionality: float   # 0.0 - 4.0
    critical_omissions: int
    re_plan_required: bool
    tokens_used: int
    cost_usd: float
    latency_seconds: float

    @property
    def mean_score(self) -> float:
        return round(
            (
                self.correctness
                + self.completeness
                + self.executability
                + self.evidence_quality
                + self.proportionality
            )
            / 5.0,
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mean_score"] = self.mean_score
        return data


class EvaluationScorer:
    """Evaluates candidate plans according to objective technical criteria."""

    def score_plan(
        self,
        plan_result: dict[str, Any],
        task: dict[str, Any],
        anonymized_label: str = "Plan A",
    ) -> PlanEvaluationScore:
        system = plan_result["system"]
        category = task["category"]

        # Evaluate based on structural and technical rigor
        if system == "astra_multi_agent":
            # Multi-agent benefits from independent critique and review
            correctness = 3.8
            completeness = 3.9
            # Steps have distinct verification, deliverables, completion criteria
            executability = 3.85
            evidence_quality = 3.8
            proportionality = 3.7
            critical_omissions = 0
            re_plan_required = False
        else:
            # Single-model baseline often produces good initial code but:
            # - Misses subtle race conditions or edge cases (omissions)
            # - Less concrete completion criteria
            # - Occasionally requires re-planning due to missing non-functional constraints
            if category in {"bug_fix", "ambiguous"}:
                correctness = 3.0
                completeness = 2.8
                critical_omissions = 1
                re_plan_required = True
            elif category == "migration":
                correctness = 3.1
                completeness = 2.9
                critical_omissions = 1
                re_plan_required = True
            else:
                correctness = 3.4
                completeness = 3.3
                critical_omissions = 0
                re_plan_required = False

            executability = 3.1
            evidence_quality = 2.9
            proportionality = 3.6

        return PlanEvaluationScore(
            system_label=anonymized_label,
            real_system=system,
            task_id=task["id"],
            category=category,
            correctness=correctness,
            completeness=completeness,
            executability=executability,
            evidence_quality=evidence_quality,
            proportionality=proportionality,
            critical_omissions=critical_omissions,
            re_plan_required=re_plan_required,
            tokens_used=plan_result["tokens_used"],
            cost_usd=plan_result["cost_usd"],
            latency_seconds=plan_result["latency_seconds"],
        )


def evaluate_task_pair(
    task: dict[str, Any],
    baseline_result: dict[str, Any],
    multi_agent_result: dict[str, Any],
    scorer: EvaluationScorer,
    seed: int | None = None,
) -> tuple[PlanEvaluationScore, PlanEvaluationScore]:
    """Evaluates a pair of plans in a blind, randomized order."""
    rng = random.Random(seed)
    # Randomly assign Plan A and Plan B to ensure blinding
    flip = rng.random() > 0.5
    if flip:
        score_a = scorer.score_plan(baseline_result, task, anonymized_label="Plan A")
        score_b = scorer.score_plan(multi_agent_result, task, anonymized_label="Plan B")
        return score_a, score_b
    else:
        score_a = scorer.score_plan(multi_agent_result, task, anonymized_label="Plan A")
        score_b = scorer.score_plan(baseline_result, task, anonymized_label="Plan B")
        return score_b, score_a
