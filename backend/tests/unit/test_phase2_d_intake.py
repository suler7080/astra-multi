"""Test suite for Phase 2 [D]: Intake nhận ràng buộc, đầu ra mong muốn và acceptance thật."""

import argparse
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.cli import build_parser, cmd_create
from astra_multi.domain.models import (
    PlanRevision,
    PlanStep,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.persistence.sqlite import SQLiteStore


def test_api_intake_constraints_non_goals_expected_outputs_and_coverage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        app = create_app(db_path=db_path)
        client = TestClient(app)

        payload = {
            "goal": "Design multi-agent engine",
            "requirements": [
                "Agent coordination with leader election",
                {"text": "State persistence in SQLite", "acceptance": "All state transitions stored"},
            ],
            "constraints": ["Zero memory leaks", "Timeout under 30s"],
            "non_goals": ["No mobile support"],
            "expected_outputs": [
                "Architecture specification markdown",
                "Schema validation contracts",
                "Recovery runbook",
            ],
        }

        res = client.post("/api/runs", json=payload)
        assert res.status_code == 202, res.text
        run_id = res.json()["run_id"]

        store = app.state.store
        run_state = store.load(run_id)
        task = run_state.task

        # 1. Check constraints and non_goals
        assert task.constraints == ["Zero memory leaks", "Timeout under 30s"]
        assert task.non_goals == ["No mobile support"]

        # 2. Check requirements count: 2 requirements + 3 expected_outputs = 5 requirements
        assert len(task.requirements) == 5
        req_ids = [r.id for r in task.requirements]
        assert req_ids == ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]

        # 3. Check acceptance format
        # REQ-001 (default acceptance without hardcode)
        assert task.requirements[0].text == "Agent coordination with leader election"
        assert task.requirements[0].acceptance == "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: Agent coordination with leader election"
        assert "Verified by design and candidate test steps" not in task.requirements[0].acceptance

        # REQ-002 (custom acceptance)
        assert task.requirements[1].text == "State persistence in SQLite"
        assert task.requirements[1].acceptance == "All state transitions stored"

        # REQ-003, REQ-004, REQ-005 (expected outputs)
        assert task.requirements[2].text == "Architecture specification markdown"
        assert task.requirements[2].acceptance == "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: Architecture specification markdown"

        assert task.requirements[3].text == "Schema validation contracts"
        assert task.requirements[3].acceptance == "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: Schema validation contracts"

        assert task.requirements[4].text == "Recovery runbook"
        assert task.requirements[4].acceptance == "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: Recovery runbook"

        # 4. RULE-COV-001: Plan missing 3rd expected_output (REQ-005) MUST FAIL
        plan_missing_req5 = PlanRevision(
            id="PLAN-1",
            run_id=run_id,
            revision=1,
            based_on_revision=0,
            requirements_revision=1,
            snapshot_id=None,
            steps=[
                PlanStep(
                    id="STEP-1",
                    objective="Leader election",
                    requirement_ids=["REQ-001"],
                    validation="test 1",
                    deliverables=["leader.py"],
                    completion_criteria=["tests pass"],
                ),
                PlanStep(
                    id="STEP-2",
                    objective="SQLite state",
                    requirement_ids=["REQ-002"],
                    validation="test 2",
                    deliverables=["db.py"],
                    completion_criteria=["tests pass"],
                ),
                PlanStep(
                    id="STEP-3",
                    objective="Arch doc",
                    requirement_ids=["REQ-003"],
                    validation="test 3",
                    deliverables=["arch.md"],
                    completion_criteria=["tests pass"],
                ),
                PlanStep(
                    id="STEP-4",
                    objective="Schema contracts",
                    requirement_ids=["REQ-004"],
                    validation="test 4",
                    deliverables=["schemas.py"],
                    completion_criteria=["tests pass"],
                ),
                # REQ-005 is missing!
            ],
        )

        validator = StructuralQualityValidator()
        report = validator.validate(run_state.model_copy(update={"plans": [plan_missing_req5]}))
        assert not report.passed
        cov_violations = [v for v in report.violations if v.rule_id == "RULE-COV-001"]
        assert len(cov_violations) == 1
        assert "REQ-005" in cov_violations[0].message

        # Now add step covering REQ-005
        plan_complete = PlanRevision(
            id="PLAN-2",
            run_id=run_id,
            revision=2,
            based_on_revision=1,
            requirements_revision=1,
            snapshot_id=None,
            steps=plan_missing_req5.steps + [
                PlanStep(
                    id="STEP-5",
                    objective="Recovery runbook",
                    requirement_ids=["REQ-005"],
                    validation="test 5",
                    deliverables=["runbook.md"],
                    completion_criteria=["tests pass"],
                )
            ],
        )

        report_complete = validator.validate(run_state.model_copy(update={"plans": [plan_complete]}))
        assert not any(v.rule_id == "RULE-COV-001" for v in report_complete.violations)
        app.state.store.close()


def test_cli_cmd_create_with_constraints_non_goals_and_expected_outputs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            parser = build_parser()

            args = parser.parse_args([
                "create",
                "--run-id", "RUN-CLI-001",
                "--goal", "Test CLI intake",
                "--requirements", "Req CLI 1", '{"text": "Req CLI 2", "acceptance": "Acc 2"}',
                "--constraints", "Constraint 1",
                "--non-goals", "Non goal 1",
                "--expected-outputs", "Output CLI 1", "Output CLI 2",
            ])

            rc = cmd_create(store, args)
            assert rc == 0

            # Retrieve created task
            task = store.load("RUN-CLI-001").task
            assert len(task.requirements) == 4
            assert task.constraints == ["Constraint 1"]
            assert task.non_goals == ["Non goal 1"]
            assert task.requirements[0].text == "Req CLI 1"
            assert task.requirements[0].acceptance == "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: Req CLI 1"
            assert task.requirements[1].text == "Req CLI 2"
            assert task.requirements[1].acceptance == "Acc 2"
            assert task.requirements[2].text == "Output CLI 1"
            assert task.requirements[3].text == "Output CLI 2"
