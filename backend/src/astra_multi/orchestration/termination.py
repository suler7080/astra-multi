"""Termination policies, stagnation detection, and stop conditions.

P3.4 Termination & Stop Conditions:
- Detects stagnation: when a revision loop produces no new evidence, no resolved issues, and no changed decisions.
- Bounded loop conditions: max review/revise rounds reached.
- Typed stop reasons.
- Cancellation flags and handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from astra_multi.domain.models import IssueStatus, RunState


class StopReason(str, Enum):
    COMPLETED = "Completed all review cycles successfully"
    MAX_ROUNDS_REACHED = "Max review/revise rounds reached"
    STAGNATION_DETECTED = "Stagnation: No new evidence or issue resolution between rounds"
    BUDGET_EXHAUSTED = "Budget limit exhausted"
    USER_CANCELLED = "Run cancelled by user request"
    WAITING_FOR_INPUT = "Waiting for required user input"
    UNRESOLVED_BLOCKERS = "Stopping: Unresolved blocking issues remain"


@dataclass
class RoundSnapshot:
    round_number: int
    open_issue_count: int
    resolved_issue_count: int
    evidence_count: int
    decision_count: int


class StagnationDetector:
    """Detects if repeated revise loops are not making forward progress."""

    def __init__(self, history_window: int = 2) -> None:
        self.history_window = history_window
        self.snapshots: list[RoundSnapshot] = []

    def record_round(self, state: RunState, round_number: int) -> None:
        open_issues = sum(
            1
            for i in state.issues
            if i.status in (IssueStatus.OPEN, IssueStatus.INVESTIGATING, IssueStatus.PROPOSED_RESOLUTION)
        )
        resolved_issues = sum(
            1 for i in state.issues if i.status == IssueStatus.RESOLVED
        )
        snap = RoundSnapshot(
            round_number=round_number,
            open_issue_count=open_issues,
            resolved_issue_count=resolved_issues,
            evidence_count=len(state.evidence),
            decision_count=len(state.decisions),
        )
        self.snapshots.append(snap)

    def is_stagnant(self) -> bool:
        """Returns True if there is no progress over the history window."""
        if len(self.snapshots) < self.history_window:
            return False

        last = self.snapshots[-1]
        prev = self.snapshots[-2]

        # If no issues were resolved, no new evidence was found, and no new decisions were made
        no_issue_progress = last.resolved_issue_count <= prev.resolved_issue_count
        no_evidence_progress = last.evidence_count <= prev.evidence_count
        no_decision_progress = last.decision_count <= prev.decision_count

        return no_issue_progress and no_evidence_progress and no_decision_progress
