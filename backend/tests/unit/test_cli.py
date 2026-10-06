"""Tests for Astra Multi CLI lifecycle and recovery (P3.5)."""

import json
import tempfile
from pathlib import Path

from astra_multi.cli import main
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import Question, RunPhase, RunStatus
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.persistence.sqlite import SQLiteStore


def test_cli_create_and_status(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "cli_test.db")

        # Create run
        ret = main([
            "--db", db_path,
            "create",
            "--goal", "Build modern auth service",
            "--requirements", "Support OAuth2", "Support JWT validation",
            "--run-id", "RUN-CLI-1",
        ])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Created run RUN-CLI-1" in captured.out

        # Query status
        ret = main(["--db", db_path, "status", "RUN-CLI-1"])
        assert ret == 0
        captured = capsys.readouterr()
        status_info = json.loads(captured.out)
        assert status_info["run_id"] == "RUN-CLI-1"
        assert status_info["phase"] == "INTAKE"
        assert status_info["status"] == "RUNNING"


def test_cli_cancel(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "cli_test.db")

        # Create
        main([
            "--db", db_path,
            "create",
            "--goal", "Test cancellation",
            "--requirements", "Requirement 1",
            "--run-id", "RUN-CANCEL-1",
        ])

        # Cancel
        ret = main([
            "--db", db_path,
            "cancel", "RUN-CANCEL-1",
            "--reason", "Aborted by user",
        ])
        assert ret == 0
        capsys.readouterr()  # clear buffer

        # Verify status is CANCELLED
        main(["--db", db_path, "status", "RUN-CANCEL-1"])
        captured = capsys.readouterr()
        status_info = json.loads(captured.out)
        assert status_info["status"] == "CANCELLED"
        assert status_info["stop_reason"] == "Aborted by user"


def test_cli_answer_question(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "cli_test.db"
        with SQLiteStore(db_file) as store:
            state = sample_state(run_id="RUN-Q-1")
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker", ttl=30)
            controller = WorkflowController(store, lease)

            # Add question
            q = Question(
                id="Q-01",
                run_id=state.run.id,
                text="Which database engine should be used?",
                blocking=True,
            )
            controller.ask_question(q)
            controller.transition_phase(RunPhase.INTAKE, RunStatus.WAITING_FOR_INPUT)
            store.release(lease)

        # Answer via CLI
        ret = main([
            "--db", str(db_file),
            "answer", "RUN-Q-1", "Q-01",
            "--answer", "Use PostgreSQL 15+",
        ])
        assert ret == 0
        capsys.readouterr()  # clear buffer

        # Check status shows 0 pending questions
        main(["--db", str(db_file), "status", "RUN-Q-1"])
        captured = capsys.readouterr()
        status_info = json.loads(captured.out)
        assert len(status_info["pending_questions"]) == 0


def test_cli_logs(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "cli_test.db")

        # Create
        main([
            "--db", db_path,
            "create",
            "--goal", "Test logging",
            "--requirements", "Req 1",
            "--run-id", "RUN-LOG-1",
        ])
        capsys.readouterr()

        # View logs plain text
        ret = main(["--db", db_path, "logs", "RUN-LOG-1"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "EXECUTION LOGS: RUN-LOG-1" in captured.out
        assert "Run created for goal: Test logging" in captured.out

        # View logs json
        ret_json = main(["--db", db_path, "logs", "RUN-LOG-1", "--json"])
        assert ret_json == 0
        captured_json = capsys.readouterr()
        data = json.loads(captured_json.out)
        assert isinstance(data, list)
        assert len(data) >= 1

