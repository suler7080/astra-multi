"""Test suite for Phase 1 [C]: Bỏ các validator tự điền dữ liệu trong agents/roles.py."""

import pytest
from pydantic import ValidationError

from astra_multi.agents.roles import (
    StepDraft,
    SynthesizerOutput,
)


def test_step_draft_empty_requirement_ids_raises_validation_error():
    """StepDraft với requirement_ids=[] -> raise ValidationError."""
    with pytest.raises(ValidationError):
        StepDraft(
            objective="Build caching layer",
            requirement_ids=[],
            validation="pytest",
            deliverables=["Cache implementation"],
            completion_criteria=["All tests pass"],
        )


def test_step_draft_empty_deliverables_raises_validation_error():
    """StepDraft với deliverables=[] -> raise ValidationError."""
    with pytest.raises(ValidationError):
        StepDraft(
            objective="Build caching layer",
            requirement_ids=["REQ-001"],
            validation="pytest",
            deliverables=[],
            completion_criteria=["All tests pass"],
        )


def test_step_draft_empty_completion_criteria_raises_validation_error():
    """StepDraft với completion_criteria=[] -> raise ValidationError."""
    with pytest.raises(ValidationError):
        StepDraft(
            objective="Build caching layer",
            requirement_ids=["REQ-001"],
            validation="pytest",
            deliverables=["Cache implementation"],
            completion_criteria=[],
        )


def test_synthesizer_output_invalid_issues_addressed_raises_validation_error():
    """issues_addressed với ID không hợp lệ -> raise ValidationError (không tự sinh ISSUE-1)."""
    step = StepDraft(
        objective="Build caching layer",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["Cache implementation"],
        completion_criteria=["All tests pass"],
    )
    with pytest.raises(ValidationError):
        SynthesizerOutput(
            steps=[step],
            decisions=[],
            risks=[],
            issues_addressed=["invalid issue id with spaces & symbols!!"],
            rationale="Attempting to address invalid issue",
        )


def test_no_spoofing_fallback_strings_in_roles_module():
    """Codebase check: không còn chuỗi 'Deliverable artifact' hay 'Completion verified' trong astra_multi."""
    import inspect
    import astra_multi.agents.roles as roles_mod

    source = inspect.getsource(roles_mod)
    assert "Deliverable artifact" not in source
    assert "Completion verified" not in source
