"""P2 / C-3: gate FINAL không được coi thiếu semantic review assessment là hợp lệ.

Trước khi sửa:
- graph.quality_gate_node coi `sem_assessment and not sem_assessment.passed`
  ⇒ assessment None (không lưu được / chạy node) bị coi là PASS.
- FinalizationService.evaluate coi None là FAIL
  (pillar rubric_audit = "Semantic review assessment not provided").
Hai nơi mâu thuẫn ⇒ một run có thể FINAL dù không có assessment.

Sau khi sửa: gate fail-closed, None → FAIL (khớp finalize), lỗi lưu assessment
trong SQLiteStore.save_semantic_review không còn bị `except Exception: pass` nuốt.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.exports.finalization import FinalizationService, SemanticReviewAssessment
from astra_multi.orchestration.graph import create_workflow_graph
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.sqlite import SQLiteStore


# ---------------------------------------------------------------------------
# Harness: state sạch + gate node qua API công khai (như test_f008)
# ---------------------------------------------------------------------------


def _clean_state() -> Any:
    state = sample_state()
    plan = sample_plan(state)
    return state.model_copy(update={"plans": [plan]})


def _gate_result(state: Any, assessment: Any, *, round_num: int = 0, max_rounds: int = 2) -> dict[str, Any]:
    ctrl = MagicMock()
    ctrl.get_state.return_value = state
    ctrl.get_semantic_review = MagicMock(return_value=assessment)
    wf_ctx = MagicMock(controller=ctrl, stagnation_detector=StagnationDetector())
    graph = create_workflow_graph(wf_ctx)
    return graph.nodes["gate"].runnable.invoke({"round": round_num, "max_rounds": max_rounds})


def _passed_assessment(plan_revision: int = 1) -> SemanticReviewAssessment:
    return SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=plan_revision,
        feedback="All criteria met",
        concerns=[],
        rubric_audits=[],
    )


def _failed_assessment(plan_revision: int = 1) -> SemanticReviewAssessment:
    return SemanticReviewAssessment(
        passed=False,
        reviewed_plan_revision=plan_revision,
        feedback="Open warning remains",
        concerns=["[ISSUE-001] Warning-level issue unresolved"],
        rubric_audits=[],
    )


# ---------------------------------------------------------------------------
# (a) Gate coi assessment None là FAIL
# ---------------------------------------------------------------------------


def test_gate_with_missing_semantic_review_is_not_final():
    state = _clean_state()
    result = _gate_result(state, None)
    assert result["gate_passed"] is False
    assert "Semantic review assessment not provided" in result["stop_reason"]


# ---------------------------------------------------------------------------
# (b) Gate và finalize cho cùng kết luận với cùng đầu vào (None / failed / passed)
# ---------------------------------------------------------------------------


def test_gate_and_finalize_agree_when_assessment_missing():
    state = _clean_state()
    result = _gate_result(state, None)
    decision = FinalizationService().evaluate(state, None)
    assert result["gate_passed"] is False
    assert decision.can_finalize is False
    assert (result["gate_passed"] is True) == decision.can_finalize
    assert decision.pillar_results["rubric_audit"].passed is False


def test_gate_and_finalize_agree_when_assessment_failed():
    state = _clean_state()
    assessment = _failed_assessment(1)
    result = _gate_result(state, assessment)
    decision = FinalizationService().evaluate(state, assessment)
    assert (result["gate_passed"] is True) == decision.can_finalize
    assert decision.can_finalize is False
    assert "Semantic review did not pass" in result["stop_reason"]


def test_gate_and_finalize_agree_when_assessment_passed():
    state = _clean_state()
    assessment = _passed_assessment(state.plan.revision)
    result = _gate_result(state, assessment)
    decision = FinalizationService().evaluate(state, assessment)
    assert (result["gate_passed"] is True) == decision.can_finalize
    assert decision.can_finalize is True
    assert result["gate_passed"] is True


# ---------------------------------------------------------------------------
# (c) Lưu thất bại không bị nuốt: lỗi phải xuyên qua save_semantic_review
# ---------------------------------------------------------------------------


def test_save_semantic_review_propagates_settings_write_failure(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "t1.sqlite")
    try:
        assessment = _passed_assessment()

        def boom(key: str, value: str) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(store.settings, "set_setting", boom)
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            store.save_semantic_review("RUN-TEST", assessment)
    finally:
        store.close()


def test_save_semantic_review_propagates_artifact_write_failure(tmp_path):
    store = SQLiteStore(tmp_path / "t2.sqlite")
    try:
        # Chặn mkdir semantic_reviews: path đã tồn tại là FILE,
        # do đó mkdir(parents=True, exist_ok=True) bắt buộc phải raise.
        blocker_dir = tmp_path / "artifacts"
        blocker_dir.mkdir(exist_ok=True)
        (blocker_dir / "semantic_reviews").write_text("not a directory", encoding="utf-8")
        assessment = _passed_assessment()
        with pytest.raises(OSError):
            store.save_semantic_review("RUN-TEST", assessment)
    finally:
        store.close()
