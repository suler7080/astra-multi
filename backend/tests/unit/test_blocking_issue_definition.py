"""A-1: unified definition of "blocking issue" (backend/src/astra_multi/domain/policies.py).

Trước khi sửa, hai định nghĩa tồn tại song song:
- Gate FINAL (graph.quality_gate_node) và RULE-ISSUE-001 (quality_validator) coi
  "status != RESOLVED" là đang chặn, nên issue BLOCKING ở status REJECTED/DUPLICATE
  cũng chặn FINAL.
- Semantic review (graph) và context bundle (bundle.py) dùng tập đã đóng
  {RESOLVED, DUPLICATE, REJECTED}.

Quyết định thiết kế (đã được chấp nhận): issue REJECTED hoặc DUPLICATE KHÔNG chặn
FINAL. OPEN -> REJECTED/DUPLICATE là transition hợp lệ (ISSUE_TRANSITIONS). Tất cả
nơi xác định trạng thái chặn phải qua is_open_issue_status / CLOSED_ISSUE_STATUSES.

Test hướng theo API công khai: helper (domain.policies), gate node
(graph.nodes["gate"], như test_f008), StructuralQualityValidator.validate và
ContextBuilder.build_context — không test private closure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from astra_multi.context.bundle import ContextBuilder, ContextLimits
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import Issue, IssueResolution, IssueSeverity, IssueStatus, RunPhase
from astra_multi.domain.policies import CLOSED_ISSUE_STATUSES, is_open_issue_status
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.orchestration.graph import create_workflow_graph
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.sqlite import SQLiteStore


# ---------------------------------------------------------------------------
# Fixtures nhỏ: state + issue BLOCKING ở mỗi status cần test
# ---------------------------------------------------------------------------

RESOLUTION = IssueResolution(text="Closed by review decision")


def _blocking_issue(
    state: Any,
    issue_id: str,
    status: IssueStatus,
    *,
    duplicate_of: str | None = None,
) -> Issue:
    payload: dict[str, Any] = {
        "id": issue_id,
        "run_id": state.run.id,
        "severity": IssueSeverity.BLOCKING,
        "status": status,
        "based_on_revision": 0,
        "claim": f"Blocking claim for {issue_id}",
        "impact": "Risk of incorrect behavior",
        "verification_request": "Verify the ambiguity is gone",
        "suggested_resolution": "Decide the intended behavior",
        "requirement_ids": ["REQ-001"],
    }
    if status in {IssueStatus.RESOLVED, IssueStatus.REJECTED}:
        payload["resolution"] = RESOLUTION
    if status == IssueStatus.DUPLICATE:
        payload["duplicate_of"] = duplicate_of
    return Issue.model_validate(payload)


def _state_with_issues(issues: list[Issue]) -> Any:
    state = sample_state()
    plan = sample_plan(state)
    return state.model_copy(update={"plans": [plan], "issues": issues})


_ALL_STATUSES: tuple[tuple[IssueStatus, str], ...] = (
    (IssueStatus.OPEN, "ISSUE-OPEN"),
    (IssueStatus.INVESTIGATING, "ISSUE-INVESTIGATING"),
    (IssueStatus.PROPOSED_RESOLUTION, "ISSUE-PROPOSED"),
    (IssueStatus.RESOLVED, "ISSUE-RESOLVED"),
    (IssueStatus.REJECTED, "ISSUE-REJECTED"),
    (IssueStatus.DUPLICATE, "ISSUE-DUPLICATE"),
)


def _state_with_one_issue_per_status() -> Any:
    state = sample_state()
    plan = sample_plan(state)
    issues = [
        _blocking_issue(
            state,
            issue_id,
            status,
            duplicate_of="ISSUE-RESOLVED" if status == IssueStatus.DUPLICATE else None,
        )
        for status, issue_id in _ALL_STATUSES
    ]
    return state.model_copy(update={"plans": [plan], "issues": issues})


def _still_open_ids(state: Any) -> set[str]:
    """Kỳ vọng chuẩn theo định nghĩa mới, độc lập với từng nơi implement."""
    return {i.id for i in state.issues if is_open_issue_status(i.status)}


# ---------------------------------------------------------------------------
# Gate node (API công khai: create_workflow_graph + node "gate", như test_f008)
# ---------------------------------------------------------------------------


def _gate_result(state: Any, *, round_num: int = 0, max_rounds: int = 2) -> dict[str, Any]:
    ctrl = MagicMock()
    ctrl.get_state.return_value = state
    wf_ctx = MagicMock(controller=ctrl, stagnation_detector=StagnationDetector())
    graph = create_workflow_graph(wf_ctx)
    return graph.nodes["gate"].runnable.invoke({"round": round_num, "max_rounds": max_rounds})


def test_blocking_issue_rejected_does_not_block_final_gate():
    state = _state_with_issues([_blocking_issue(sample_state(), "ISSUE-REJ", IssueStatus.REJECTED)])
    result = _gate_result(state)
    assert result["gate_passed"] is True
    assert result["stop_reason"] == ""


def test_blocking_issue_duplicate_does_not_block_final_gate():
    state = _state_with_issues(
        [
            # duplicate phải trỏ tới một issue gốc khác (RESOLVED) cho hợp lệ
            _blocking_issue(sample_state(), "ISSUE-CANONICAL", IssueStatus.RESOLVED),
            _blocking_issue(sample_state(), "ISSUE-DUP", IssueStatus.DUPLICATE, duplicate_of="ISSUE-CANONICAL"),
        ]
    )
    result = _gate_result(state)
    assert result["gate_passed"] is True
    assert result["stop_reason"] == ""


def test_blocking_issue_open_still_blocks_final_gate():
    state = _state_with_issues([_blocking_issue(sample_state(), "ISSUE-OPEN", IssueStatus.OPEN)])
    result = _gate_result(state)
    assert result["gate_passed"] is False
    assert "1 unresolved blocking issues" in result["stop_reason"]


# ---------------------------------------------------------------------------
# StructuralQualityValidator (API công khai: validate + QualityReport)
# ---------------------------------------------------------------------------


def test_rejected_blocking_issue_not_flagged_rule_issue_001():
    state = _state_with_issues([_blocking_issue(sample_state(), "ISSUE-REJ", IssueStatus.REJECTED)])
    report = StructuralQualityValidator().validate(state)
    rule_001 = [v for v in report.violations if v.rule_id == "RULE-ISSUE-001"]
    assert rule_001 == []
    assert set(report.unresolved_blocking_issues) == set()


def test_duplicate_blocking_issue_not_flagged_rule_issue_001():
    state = _state_with_issues(
        [
            _blocking_issue(sample_state(), "ISSUE-CANONICAL", IssueStatus.RESOLVED),
            _blocking_issue(sample_state(), "ISSUE-DUP", IssueStatus.DUPLICATE, duplicate_of="ISSUE-CANONICAL"),
        ]
    )
    report = StructuralQualityValidator().validate(state)
    rule_001 = [v for v in report.violations if v.rule_id == "RULE-ISSUE-001"]
    assert rule_001 == []
    assert set(report.unresolved_blocking_issues) == set()


def test_open_blocking_issue_still_flagged_rule_issue_001():
    state = _state_with_issues([_blocking_issue(sample_state(), "ISSUE-OPEN", IssueStatus.OPEN)])
    report = StructuralQualityValidator().validate(state)
    assert any(v.rule_id == "RULE-ISSUE-001" for v in report.violations)
    assert report.unresolved_blocking_issues == ["ISSUE-OPEN"]


# ---------------------------------------------------------------------------
# Helper thống nhất (domain.policies)
# ---------------------------------------------------------------------------


def test_closed_status_set_matches_approved_design():
    assert CLOSED_ISSUE_STATUSES == frozenset(
        {IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.DUPLICATE}
    )


@pytest.mark.parametrize("status", [IssueStatus.OPEN, IssueStatus.INVESTIGATING, IssueStatus.PROPOSED_RESOLUTION])
def test_helper_marks_unclosed_statuses_blocking(status: IssueStatus):
    assert is_open_issue_status(status) is True


@pytest.mark.parametrize("status", [IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.DUPLICATE])
def test_helper_marks_closed_statuses_not_blocking(status: IssueStatus):
    assert is_open_issue_status(status) is False


# ---------------------------------------------------------------------------
# (d) Bốn nơi cho cùng kết quả trên cùng một tập issue
# ---------------------------------------------------------------------------


def test_all_four_places_agree_on_same_issue_set(tmp_path):
    state = _state_with_one_issue_per_status()
    expected_open = _still_open_ids(state)
    # Định nghĩa mới: chỉ OPEN/INVESTIGATING/PROPOSED_RESOLUTION còn chặn.
    assert expected_open == {"ISSUE-OPEN", "ISSUE-INVESTIGATING", "ISSUE-PROPOSED"}

    # 1) Helper (đã dùng ở trên) + gate node
    result = _gate_result(state)
    assert result["gate_passed"] is False
    assert f"{len(expected_open)} unresolved blocking issues" in result["stop_reason"]

    # 2) Validator: report liệt kê đúng và chỉ đúng các issue còn chặn
    report = StructuralQualityValidator().validate(state)
    assert set(report.unresolved_blocking_issues) == expected_open
    rule_001 = [v for v in report.violations if v.rule_id == "RULE-ISSUE-001"]
    assert {v.entity_ref for v in rule_001} == {f"issue:{rid}" for rid in expected_open}

    # 3) Context bundle: issue đã đóng ra khỏi "open_issues", chỉ còn ở
    #    closed_resolutions; issue còn chặn xuất hiện ở phía open.
    store = SQLiteStore(tmp_path / "bundle.sqlite")
    try:
        builder = ContextBuilder(store.artifacts)
        bundle = builder.build_context(
            state, "planner", RunPhase.REVIEW, [], ContextLimits(max_tokens=12000)
        )
    finally:
        store.close()
    open_marker = bundle.content.find('"open_issues"')
    closed_marker = bundle.content.find('"closed_resolutions"')
    assert open_marker != -1
    assert closed_marker != -1
    # Layout thực tế của bundle content: "closed_resolutions" đứng trước
    # "open_issues" (deterministic dict ordering của baseline JSON).
    assert closed_marker < open_marker
    for rid in expected_open:
        idx = bundle.content.find(f'"{rid}"')
        assert idx != -1, (rid, bundle.content[:200])
        assert idx > open_marker, rid
    for rid in ("ISSUE-RESOLVED", "ISSUE-REJECTED", "ISSUE-DUPLICATE"):
        idx = bundle.content.find(f'"{rid}"')
        assert idx != -1, (rid, bundle.content[:200])
        assert idx < open_marker, rid
