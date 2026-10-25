"""Verification test for Test 7 under Phase 1 truth-telling quality gates.

Input:
Goal: "Thiết kế engine đa agent: agent Planner chia việc, các agent Worker thực hiện, agent Reviewer chấm và yêu cầu sửa lại, có vòng lặp cho đến khi đạt hoặc hết ngân sách."
Requirements:
- REQ-001: Giới hạn số vòng sửa tối đa và ngân sách token.
- REQ-002: Mỗi agent chỉ thấy phần ngữ cảnh cần thiết.
- REQ-003: Phải khôi phục được khi một agent lỗi giữa chừng.
- REQ-004: Toàn bộ trạng thái ghi log để kiểm toán.

Outcome expectation in Phase 1:
Run MUST terminate with PARTIAL (not FINAL) because open warning issues block finalization.
"""

import sqlite3
from pathlib import Path

from astra_multi.domain.models import RunState, RunStatus
from astra_multi.exports.finalization import FinalizationService
from astra_multi.exports.quality_validator import StructuralQualityValidator


def test_test7_state_under_phase1_gates_terminates_partial():
    db_path = Path(__file__).resolve().parents[2] / "backend" / ".local" / "domain.sqlite"

    import pytest

    if not db_path.exists():
        pytest.skip(
            f"Historical run database not found at {db_path} (runtime data, not tracked)"
        )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT state_json FROM runs WHERE id='RUN-a329f6d3'").fetchone()
    if row is None:
        pytest.skip("Historical run RUN-a329f6d3 not found in local runs")

    state = RunState.model_validate_json(row[0])
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    # 1. Structural gate MUST fail due to open warning issues
    assert report.passed is False
    blockers = [v for v in report.violations if v.rule_id == "RULE-ISSUE-002"]
    assert len(blockers) == 3  # exactly the 3 open warning issues

    # 2. Finalization evaluation MUST reject FINAL and target PARTIAL
    service = FinalizationService(validator=validator)
    decision = service.evaluate(state)
    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert "RULE-ISSUE-002" in decision.reason or "remains open" in decision.reason
