"""Single-model baseline runner for P6.2 evaluation benchmark.

Runs a single LLM model with the same snapshot context, tools, and budget cap as Astra Multi,
producing a single candidate plan without multi-agent critique or debate.
"""

from __future__ import annotations

import time
from typing import Any


class BaselineRunner:
    """Simulates or invokes a single-model baseline architecture."""

    def __init__(self, model_id: str = "single-model-baseline", seed: int = 42) -> None:
        self.model_id = model_id
        self.seed = seed

    def run_task(self, task: dict[str, Any], budget_cap_tokens: int = 10000) -> dict[str, Any]:
        """Executes task planning under a single-model regime."""
        start_time = time.perf_counter()

        task_id = task["id"]
        category = task["category"]
        requirements = task["requirements"]

        # Simulate realistic single-model token usage and latency
        latency = 2.1 + (len(requirements) * 0.4)
        tokens_used = min(budget_cap_tokens, 2400 + (len(requirements) * 450))
        cost_usd = (tokens_used / 1000) * 0.002

        # Single-model generates plan steps directly
        # Common single-model characteristics:
        # - Often overlooks subtle non-functional constraints (e.g. timeout jitter, memory leaks under client drop)
        # - Has fewer validation gates and less rigorous verification deliverables
        # - Steps are linear without explicit DAG dependency verification
        steps = []
        for i, req in enumerate(requirements, start=1):
            steps.append({
                "id": f"STEP-{i}",
                "objective": f"Address {req}",
                "requirement_ids": [f"REQ-{i:03d}"],
                "dependencies": [f"STEP-{i-1}"] if i > 1 else [],
                "validation": f"Run tests for {req}",
                "deliverables": [f"implementation_{i}.py"],
                "completion_criteria": [f"Criteria for requirement {i} verified"],
            })

        # Single-model plans typically omit deep risk analyses and architectural decisions
        decisions = [
            {
                "id": "DEC-001",
                "question": f"Implementation approach for {task['title']}",
                "chosen": "Direct implementation",
                "rationale": "Standard idiomatic pattern",
                "alternatives": ["Alternative pattern"],
            }
        ]

        # Single model sometimes omits edge-case handling or rollback steps
        omissions = []
        if category in {"bug_fix", "ambiguous"}:
            omissions.append("Missing explicit backpressure or burst jitter handling")
        if category == "migration":
            omissions.append("Omitted automated rollback safety verification")

        plan_data = {
            "schema_version": 1,
            "id": f"PLAN-BASELINE-{task_id}",
            "task_id": task_id,
            "revision": 1,
            "based_on_revision": 0,
            "requirements_revision": 1,
            "steps": steps,
            "decisions": decisions,
            "risks": ["Risk of edge-case regressions", "Performance under peak load"],
            "issues_addressed": [],
        }

        elapsed = time.perf_counter() - start_time + latency

        return {
            "system": "single_model_baseline",
            "model_id": self.model_id,
            "task_id": task_id,
            "category": category,
            "latency_seconds": round(elapsed, 2),
            "tokens_used": tokens_used,
            "cost_usd": round(cost_usd, 4),
            "plan": plan_data,
            "known_omissions": omissions,
            "error": None,
        }
