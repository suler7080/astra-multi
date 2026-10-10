"""Tests for FIX-07: StagnationDetector history_window configuration and issue discovery progress.

Verifies:
1. StagnationDetector respects history_window > 2 by comparing against snapshots[-history_window].
2. StagnationDetector recognizes discovering new issues as forward progress.
3. StagnationDetector clamps history_window to a minimum of 2.
4. Preserves backward compatibility for default history_window=2.
"""

from __future__ import annotations

from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    Evidence,
    Issue,
    IssueSeverity,
    IssueStatus,
    utc_now,
)
from astra_multi.orchestration.termination import StagnationDetector


def test_stagnation_detector_respects_history_window_greater_than_two():
    """When history_window=3, stagnation is evaluated over the 3-round window, not just the last 2 rounds."""
    detector = StagnationDetector(history_window=3)
    state = sample_state()

    # Round 1: baseline (0 evidence)
    detector.record_round(state, round_number=1)
    assert not detector.is_stagnant()

    # Round 2: progress made (added 1 evidence)
    evi = Evidence(
        id="EVI-1",
        run_id=state.run.id,
        source_type="user",
        locator="spec.md",
        content_hash="a" * 64,
        captured_at=utc_now(),
        snapshot_id=None,
    )
    state_with_evi = state.model_copy(update={"evidence": [evi]})
    detector.record_round(state_with_evi, round_number=2)
    # Still less than 3 snapshots
    assert not detector.is_stagnant()

    # Round 3: no new progress compared to Round 2, but progress exists compared to Round 1 (baseline of window 3)
    detector.record_round(state_with_evi, round_number=3)
    # In old code: compared Round 3 with Round 2, falsely declaring stagnation!
    # In new code: compared Round 3 with Round 1 (1 evidence > 0 evidence), correctly declared not stagnant.
    assert not detector.is_stagnant()

    # Round 4: no changes. Window [Round 2, Round 3, Round 4]. Baseline is Round 2 (1 evidence). Round 4 has 1 evidence.
    detector.record_round(state_with_evi, round_number=4)
    # Now across the 3-round window [2, 3, 4], no progress was made -> stagnant!
    assert detector.is_stagnant()


def test_stagnation_detector_recognizes_new_issue_discovery_as_progress():
    """Discovering a new issue during investigation is considered active forward progress."""
    detector = StagnationDetector(history_window=2)
    state = sample_state()

    # Round 1: 0 issues
    detector.record_round(state, round_number=1)
    assert not detector.is_stagnant()

    # Round 2: A new issue is discovered and recorded (status OPEN)
    new_issue = Issue(
        id="ISSUE-NEW-1",
        run_id=state.run.id,
        severity=IssueSeverity.WARNING,
        based_on_revision=0,
        claim="New discovered defect",
        impact="Low",
        verification_request="Verify defect",
        suggested_resolution="Fix code",
        requirement_ids=[state.task.requirements[0].id],
        status=IssueStatus.OPEN,
    )
    state_with_issue = state.model_copy(update={"issues": [new_issue]})
    detector.record_round(state_with_issue, round_number=2)

    # Active discovery of issues indicates investigation progress, not stagnation
    assert not detector.is_stagnant()


def test_stagnation_detector_clamps_minimum_history_window():
    """history_window is clamped to at least 2 to ensure a valid multi-round delta."""
    detector = StagnationDetector(history_window=1)
    assert detector.history_window == 2

    detector_zero = StagnationDetector(history_window=0)
    assert detector_zero.history_window == 2


def test_stagnation_detector_legacy_default_behavior():
    """Default history_window=2 triggers stagnation when 2 consecutive rounds have no progress."""
    detector = StagnationDetector(history_window=2)
    state = sample_state()

    detector.record_round(state, round_number=1)
    assert not detector.is_stagnant()

    detector.record_round(state, round_number=2)
    assert detector.is_stagnant()
