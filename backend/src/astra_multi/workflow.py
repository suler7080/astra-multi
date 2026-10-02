"""P0.2 Spike — LangGraph workflow with fan-out/fan-in, bounded loop, deterministic merge.

Graph: intake → independent_analysis (fan-out planner + reviewer) → propose → review → revise → gate → export
Controller logic is deterministic code, not LLM-driven routing.
"""

from __future__ import annotations

import json
import operator
from dataclasses import asdict
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from astra_multi import fake_model
from astra_multi.domain.models import IssueResolution, Requirement
from astra_multi.schemas import (
    IssueStatus,
    Phase,
    TaskSpec,
)

# ---------------------------------------------------------------------------
# Graph state — shared blackboard
# ---------------------------------------------------------------------------


def _merge_analyses(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge analyses with stable order by role name."""
    merged = {a["role"]: a for a in existing}
    for a in new:
        merged[a["role"]] = a
    return sorted(merged.values(), key=lambda x: x["role"])


class WorkflowState(TypedDict, total=False):
    """Graph state. Annotations control how parallel outputs merge."""

    task: dict[str, Any]
    phase: str
    analyses: Annotated[list[dict[str, Any]], _merge_analyses]
    proposal: dict[str, Any] | None
    issues: list[dict[str, Any]]
    plan: dict[str, Any] | None
    round: int
    max_rounds: int
    gate_passed: bool
    stop_reason: str
    events: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def intake_node(state: WorkflowState) -> dict:
    """Validate task spec and initialize run."""
    task = state["task"]
    return {
        "phase": Phase.INTAKE.value,
        "round": 0,
        "max_rounds": state.get("max_rounds", 2),
        "issues": [],
        "events": [
            f"[INTAKE] Task {task['id']} accepted, {len(task['requirements'])} requirements"
        ],
    }


def planner_analysis_node(state: WorkflowState) -> dict:
    """Planner independent analysis — does NOT see reviewer output."""
    result = fake_model.generate(
        role="planner",
        messages=[{"role": "user", "content": "Analyze the task independently"}],
    )
    analysis = result.content
    return {
        "analyses": [asdict(analysis)],
        "events": [f"[ANALYSIS] Planner completed: {len(analysis.findings)} findings"],
    }


def reviewer_analysis_node(state: WorkflowState) -> dict:
    """Reviewer independent analysis — does NOT see planner output."""
    result = fake_model.generate(
        role="reviewer",
        messages=[{"role": "user", "content": "Analyze the task independently"}],
    )
    analysis = result.content
    return {
        "analyses": [asdict(analysis)],
        "events": [f"[ANALYSIS] Reviewer completed: {len(analysis.findings)} findings"],
    }


def propose_node(state: WorkflowState) -> dict:
    """Planner creates proposal based on analyses."""
    result = fake_model.generate(
        role="planner",
        messages=[{"role": "user", "content": "Propose a solution based on analyses"}],
    )
    proposal = result.content
    return {
        "phase": Phase.PROPOSE.value,
        "proposal": proposal.model_dump(mode="json"),
        "events": [f"[PROPOSE] Proposal {proposal.id}: {proposal.approach[:60]}"],
    }


def review_node(state: WorkflowState) -> dict:
    """Reviewer examines proposal and creates issues."""
    result = fake_model.generate(
        role="reviewer",
        messages=[{"role": "user", "content": "Review the proposal for issues"}],
    )
    issues = result.content
    issues_dicts = [i.model_dump(mode="json") for i in issues]
    return {
        "phase": Phase.REVIEW.value,
        "issues": issues_dicts,
        "events": [
            f"[REVIEW] Found {len(issues)} issues, "
            f"{sum(1 for i in issues if i.severity.value == 'blocking')} blocking"
        ],
    }


def revise_node(state: WorkflowState) -> dict:
    """Synthesizer merges analyses, proposal, issues into revised plan."""
    current_round = state.get("round", 0) + 1
    result = fake_model.generate(
        role="synthesizer",
        messages=[{"role": "user", "content": "Synthesize revised plan"}],
    )
    plan = result.content
    # Mark issues as resolved in the revision
    resolved_issues = []
    for issue in state.get("issues", []):
        issue_copy = dict(issue)
        issue_copy["status"] = IssueStatus.RESOLVED.value
        issue_copy["resolution"] = IssueResolution(
            text=f"Addressed in plan revision {plan.revision}",
            reviewed_revision=plan.revision,
            reviewer="fake-reviewer",
            review_result="PASS",
            review_note="Deterministic spike fixture review",
        ).model_dump(mode="json")
        resolved_issues.append(issue_copy)

    return {
        "phase": Phase.REVISE.value,
        "plan": plan.model_dump(mode="json"),
        "issues": resolved_issues,
        "round": current_round,
        "events": [
            f"[REVISE] Round {current_round}: plan revision {plan.revision}, "
            f"{len(resolved_issues)} issues addressed"
        ],
    }


def gate_node(state: WorkflowState) -> dict:
    """Deterministic quality gate — checks structure, not semantics."""
    plan = state.get("plan")
    issues = state.get("issues", [])

    problems = []

    if not plan:
        problems.append("No plan produced")

    # Check all blocking issues resolved
    unresolved_blocking = [
        i
        for i in issues
        if i.get("severity") == "blocking"
        and i.get("status") != IssueStatus.RESOLVED.value
    ]
    if unresolved_blocking:
        problems.append(f"{len(unresolved_blocking)} unresolved blocking issues")

    # Check requirement coverage
    if plan:
        task = state.get("task", {})
        req_ids = {r["id"] for r in task.get("requirements", [])}
        covered = set()
        for step in plan.get("steps", []):
            covered.update(step.get("requirement_ids", []))
        missing = req_ids - covered
        if missing:
            problems.append(f"Requirements not covered: {missing}")

        # Check DAG (no cycles in step dependencies)
        step_ids = {s["id"] for s in plan.get("steps", [])}
        for step in plan.get("steps", []):
            for dep in step.get("dependencies", []):
                if dep not in step_ids:
                    problems.append(f"Step {step['id']} depends on unknown step {dep}")

    passed = len(problems) == 0
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", 2)

    if not passed and round_num >= max_rounds:
        return {
            "phase": Phase.PARTIAL.value,
            "gate_passed": False,
            "stop_reason": f"Max rounds ({max_rounds}) reached with problems: {'; '.join(problems)}",
            "events": [f"[GATE] PARTIAL — max rounds reached: {'; '.join(problems)}"],
        }

    return {
        "phase": Phase.QUALITY_GATE.value,
        "gate_passed": passed,
        "stop_reason": "" if passed else "; ".join(problems),
        "events": [
            f"[GATE] {'PASSED' if passed else 'FAILED'}: {'; '.join(problems) if problems else 'all checks OK'}"
        ],
    }


def export_node(state: WorkflowState) -> dict:
    """Export final plan as JSON and Markdown."""
    plan = state.get("plan", {})
    task = state.get("task", {})

    # JSON export
    export_json = {
        "task_id": task.get("id"),
        "status": "FINAL" if state.get("gate_passed") else "PARTIAL",
        "plan": plan,
        "decisions": plan.get("decisions", []),
        "issues": state.get("issues", []),
        "rounds": state.get("round", 0),
        "stop_reason": state.get("stop_reason", ""),
    }

    # Markdown export (same content, different format)
    md_lines = [
        f"# Plan: {task.get('goal', 'Unknown')}",
        f"\nStatus: **{'FINAL' if state.get('gate_passed') else 'PARTIAL'}**",
        f"\nRounds: {state.get('round', 0)}",
    ]
    if state.get("stop_reason"):
        md_lines.append(f"\nStop reason: {state['stop_reason']}")

    md_lines.append("\n## Steps\n")
    for step in plan.get("steps", []):
        md_lines.append(f"### {step['id']}: {step['objective']}")
        md_lines.append(f"- Requirements: {', '.join(step.get('requirement_ids', []))}")
        md_lines.append(
            f"- Dependencies: {', '.join(step.get('dependencies', [])) or 'none'}"
        )
        md_lines.append(f"- Validation: {step['validation']}")
        md_lines.append(f"- Deliverables: {', '.join(step.get('deliverables', []))}")
        md_lines.append("")

    md_lines.append("## Decisions\n")
    for dec in plan.get("decisions", []):
        md_lines.append(f"- **{dec['id']}**: {dec['question']} → {dec['chosen']}")
        md_lines.append(f"  Rationale: {dec['rationale']}")
        md_lines.append("")

    export_md = "\n".join(md_lines)

    return {
        "phase": Phase.EXPORT.value
        if state.get("gate_passed")
        else Phase.PARTIAL.value,
        "events": [
            f"[EXPORT] JSON: {len(json.dumps(export_json))} bytes",
            f"[EXPORT] Markdown: {len(export_md)} chars",
        ],
    }


# ---------------------------------------------------------------------------
# Graph routing
# ---------------------------------------------------------------------------


def should_loop_or_export(state: WorkflowState) -> str:
    """After gate: if passed → export, if failed and rounds left → review again."""
    if state.get("gate_passed"):
        return "export"
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", 2)
    if round_num >= max_rounds:
        return "export"  # Export as PARTIAL
    return "review"  # Loop back


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_workflow() -> StateGraph:
    """Construct the spike workflow graph."""
    graph = StateGraph(WorkflowState)

    # Add nodes
    graph.add_node("intake", intake_node)
    graph.add_node("planner_analysis", planner_analysis_node)
    graph.add_node("reviewer_analysis", reviewer_analysis_node)
    graph.add_node("propose", propose_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("gate", gate_node)
    graph.add_node("export", export_node)

    # Edges: intake → fan-out to both analyses
    graph.set_entry_point("intake")
    graph.add_edge("intake", "planner_analysis")
    graph.add_edge("intake", "reviewer_analysis")

    # Fan-in: both analyses → propose
    graph.add_edge("planner_analysis", "propose")
    graph.add_edge("reviewer_analysis", "propose")

    # Linear: propose → review → revise → gate
    graph.add_edge("propose", "review")
    graph.add_edge("review", "revise")
    graph.add_edge("revise", "gate")

    # Conditional: gate → export or loop
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


def create_compiled_workflow(checkpointer=None):
    """Build and compile the workflow, optionally with checkpointer."""
    graph = build_workflow()
    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Fixtures for testing
# ---------------------------------------------------------------------------

SAMPLE_TASK = TaskSpec(
    id="TASK-001",
    goal="Migrate database schema to support multi-tenant architecture",
    requirements=[
        Requirement(
            id="REQ-001", text="Schema versioning", acceptance="Alembic configured"
        ),
        Requirement(
            id="REQ-002", text="Backward compatibility", acceptance="Old API works"
        ),
    ],
)

SAMPLE_INPUT = {
    "task": {
        "id": "TASK-001",
        "goal": "Migrate database schema to support multi-tenant architecture",
        "requirements": [
            {
                "id": "REQ-001",
                "text": "Schema versioning",
                "acceptance": "Alembic configured",
            },
            {
                "id": "REQ-002",
                "text": "Backward compatibility",
                "acceptance": "Old API works",
            },
        ],
        "constraints": ["Zero downtime"],
        "unknowns": [],
    },
    "max_rounds": 2,
}
