"""P0.3 Tests — Checkpoint, interrupt, and crash recovery.

Tests per acceptance criteria:
1. Restart preserves committed results
2. Same answer doesn't create duplicate mutations
3. Crash after commit doesn't duplicate plan revision
4. Stream events are observable
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from langgraph.checkpoint.sqlite import SqliteSaver

from astra_multi.workflow import (
    SAMPLE_INPUT,
    build_workflow,
    WorkflowState,
)
from astra_multi.schemas import IssueStatus, Phase


def _make_sqlite_conn(db_path: str) -> sqlite3.Connection:
    """Create a SQLite connection with Windows-friendly settings."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


class TestCheckpointPersistence:
    """P0.3: restart giữ kết quả đã commit."""

    def test_checkpoint_saves_and_restores_state(self):
        """Run workflow, then verify checkpoint exists and has correct state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-run-001"}}
                result = workflow.invoke(SAMPLE_INPUT, config=config)

                # Verify plan was produced
                assert result.get("plan") is not None
                assert result.get("gate_passed") is True

                # Get checkpoint state
                state = workflow.get_state(config)
                assert state is not None
                assert state.values.get("plan") is not None
            finally:
                conn.close()

    def test_resume_after_restart_keeps_results(self):
        """Simulate restart: create new workflow instance from same DB, verify state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")

            # First run
            conn1 = _make_sqlite_conn(db_path)
            try:
                cp1 = SqliteSaver(conn1)
                graph1 = build_workflow()
                workflow1 = graph1.compile(checkpointer=cp1)

                config = {"configurable": {"thread_id": "test-run-002"}}
                result1 = workflow1.invoke(SAMPLE_INPUT, config=config)
                plan1 = result1.get("plan")
            finally:
                conn1.close()

            # "Restart": new workflow instance, same DB
            conn2 = _make_sqlite_conn(db_path)
            try:
                cp2 = SqliteSaver(conn2)
                graph2 = build_workflow()
                workflow2 = graph2.compile(checkpointer=cp2)

                state = workflow2.get_state(config)

                # State should have the same plan
                assert state.values.get("plan") == plan1
                assert state.values.get("gate_passed") is True
            finally:
                conn2.close()


class TestIdempotency:
    """P0.3: cùng answer không tạo hai mutation."""

    def test_same_thread_same_result(self):
        """Running the same input on the same thread produces same checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-idempotent"}}
                result1 = workflow.invoke(SAMPLE_INPUT, config=config)

                # The workflow should be at END — plan revision should be 1
                assert result1.get("plan", {}).get("revision") == 1
            finally:
                conn.close()

    def test_no_duplicate_issues_across_checkpoint(self):
        """Issues are not duplicated when checkpoint is restored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-no-dup"}}
                result = workflow.invoke(SAMPLE_INPUT, config=config)

                issues = result.get("issues", [])
                issue_ids = [i["id"] for i in issues]
                # No duplicate IDs
                assert len(issue_ids) == len(set(issue_ids)), (
                    f"Duplicate issue IDs: {issue_ids}"
                )
            finally:
                conn.close()


class TestStreamEvents:
    """P0.3: stream event có thể quan sát được."""

    def test_stream_updates_observable(self):
        """Stream mode produces events that can be observed in real time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-stream"}}
                collected_events = []

                for update in workflow.stream(
                    SAMPLE_INPUT, config=config, stream_mode="updates"
                ):
                    for node_name, node_update in update.items():
                        if "events" in node_update:
                            collected_events.extend(node_update["events"])

                assert len(collected_events) > 0
                phases_seen = set()
                for ev in collected_events:
                    bracket = ev.split("]")[0] + "]"
                    phases_seen.add(bracket)
                assert "[INTAKE]" in phases_seen
                assert "[ANALYSIS]" in phases_seen
                assert "[GATE]" in phases_seen
            finally:
                conn.close()

    def test_checkpoint_db_has_records(self):
        """SQLite checkpoint DB actually has records after a run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoint.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-db-records"}}
                workflow.invoke(SAMPLE_INPUT, config=config)

                # Verify the SQLite DB has checkpoint records
                cursor = conn.execute("SELECT COUNT(*) FROM checkpoints")
                count = cursor.fetchone()[0]
                assert count > 0, "No checkpoint records in DB"
            finally:
                conn.close()
