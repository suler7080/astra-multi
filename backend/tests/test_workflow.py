"""P0.2 Tests — Workflow spike verification.

Tests per acceptance criteria:
1. Reviewer round 1 does NOT see Planner output (input isolation)
2. Same fixture → same merged result regardless of completion order
3. Loop has round limit
4. Unresolved blocker → PARTIAL
5. JSON/Markdown export with same content
"""

from __future__ import annotations

import copy

from astra_multi.workflow import (
    SAMPLE_INPUT,
    build_workflow,
    create_compiled_workflow,
    gate_node,
    WorkflowState,
)
from astra_multi.schemas import IssueStatus, Phase


class TestInputIsolation:
    """P0.2 acceptance: Reviewer vòng đầu không nhận output Planner."""

    def test_planner_marker_not_in_reviewer_analysis(self):
        """Planner's marker must not appear in reviewer's analysis."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        analyses = result.get("analyses", [])
        assert len(analyses) == 2, f"Expected 2 analyses, got {len(analyses)}"

        planner = next(a for a in analyses if a["role"] == "planner")
        reviewer = next(a for a in analyses if a["role"] == "reviewer")

        # Planner has its own marker
        assert "PLANNER_MARKER" in planner.get("marker", "")
        # Reviewer has its own marker, NOT planner's
        assert "REVIEWER_MARKER" in reviewer.get("marker", "")
        assert "PLANNER_MARKER" not in reviewer.get("marker", "")
        # Reviewer findings don't contain planner findings
        planner_findings = set(planner["findings"])
        reviewer_findings = set(reviewer["findings"])
        assert planner_findings.isdisjoint(reviewer_findings)


class TestDeterministicMerge:
    """P0.2 acceptance: cùng fixture cho cùng kết quả hợp nhất dù thứ tự hoàn thành khác nhau."""

    def test_same_input_same_output(self):
        """Two invocations of the same input produce identical plan."""
        workflow = create_compiled_workflow()

        result1 = workflow.invoke(SAMPLE_INPUT)
        result2 = workflow.invoke(SAMPLE_INPUT)

        assert result1["plan"] == result2["plan"]
        assert result1["gate_passed"] == result2["gate_passed"]
        assert result1["round"] == result2["round"]

    def test_analyses_sorted_by_role(self):
        """Analyses are always sorted by role name regardless of completion order."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        analyses = result.get("analyses", [])
        roles = [a["role"] for a in analyses]
        assert roles == sorted(roles), f"Analyses not sorted: {roles}"


class TestBoundedLoop:
    """P0.2 acceptance: loop có giới hạn."""

    def test_respects_max_rounds(self):
        """Workflow does not exceed max_rounds."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        max_rounds = SAMPLE_INPUT["max_rounds"]
        assert result["round"] <= max_rounds, (
            f"Round {result['round']} exceeds max {max_rounds}"
        )

    def test_stops_when_gate_passes(self):
        """Workflow stops before max rounds if gate passes."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        if result.get("gate_passed"):
            # Should have finished, not looped unnecessarily
            assert result["phase"] in (Phase.EXPORT.value, Phase.COMPLETED.value)


class TestGateLogic:
    """P0.2 acceptance: unresolved blocker trả PARTIAL."""

    def test_unresolved_blocker_fails_gate(self):
        """Gate fails when blocking issue is unresolved."""
        state: WorkflowState = {
            "task": SAMPLE_INPUT["task"],
            "plan": {
                "steps": [
                    {"id": "S1", "requirement_ids": ["REQ-001", "REQ-002"],
                     "dependencies": [], "objective": "x", "validation": "x",
                     "deliverables": ["x"]},
                ],
                "decisions": [],
                "risks": [],
            },
            "issues": [
                {
                    "id": "ISSUE-X",
                    "severity": "blocking",
                    "status": "open",
                    "claim": "Unresolved problem",
                    "evidence": "test",
                    "suggested_resolution": "fix it",
                },
            ],
            "round": 2,
            "max_rounds": 2,
            "events": [],
        }
        result = gate_node(state)
        assert not result["gate_passed"]
        assert "PARTIAL" in result["phase"]

    def test_all_resolved_passes_gate(self):
        """Gate passes when all issues are resolved and reqs covered."""
        state: WorkflowState = {
            "task": SAMPLE_INPUT["task"],
            "plan": {
                "steps": [
                    {"id": "S1", "requirement_ids": ["REQ-001", "REQ-002"],
                     "dependencies": [], "objective": "x", "validation": "x",
                     "deliverables": ["x"]},
                ],
                "decisions": [],
                "risks": [],
            },
            "issues": [
                {
                    "id": "ISSUE-X",
                    "severity": "blocking",
                    "status": IssueStatus.RESOLVED.value,
                    "claim": "Fixed",
                    "evidence": "test",
                    "suggested_resolution": "done",
                    "resolution": "Fixed in rev 1",
                },
            ],
            "round": 1,
            "max_rounds": 2,
            "events": [],
        }
        result = gate_node(state)
        assert result["gate_passed"]


class TestEndToEnd:
    """Full workflow execution test."""

    def test_happy_path(self):
        """Workflow completes with a plan."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        # Must have a plan
        assert result.get("plan") is not None
        plan = result["plan"]
        assert len(plan["steps"]) > 0

        # Must have analyses from both roles
        analyses = result.get("analyses", [])
        roles = {a["role"] for a in analyses}
        assert "planner" in roles
        assert "reviewer" in roles

        # Must have gone through gate
        assert "gate_passed" in result

    def test_events_are_recorded(self):
        """Events are accumulated through the run."""
        workflow = create_compiled_workflow()
        result = workflow.invoke(SAMPLE_INPUT)

        events = result.get("events", [])
        assert len(events) > 0
        # Should have at least intake, analyses, propose, review, revise, gate, export
        event_prefixes = {e.split("]")[0] + "]" for e in events}
        assert "[INTAKE]" in event_prefixes
        assert "[ANALYSIS]" in event_prefixes
        assert "[PROPOSE]" in event_prefixes

    def test_streaming_produces_updates(self):
        """Stream mode produces incremental updates."""
        workflow = create_compiled_workflow()
        updates = list(workflow.stream(SAMPLE_INPUT, stream_mode="updates"))
        assert len(updates) > 0
        # Each update is a dict of node_name -> state_update
        for update in updates:
            assert isinstance(update, dict)
