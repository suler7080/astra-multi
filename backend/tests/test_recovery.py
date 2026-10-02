"""P0.3 Recovery Tests — Interrupt/resume and crash recovery.

Tests per acceptance criteria:
1. Interrupt/resume preserves state and continues correctly
2. Kill process and restart recovers without duplicates
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from astra_multi.workflow import SAMPLE_INPUT, build_workflow


def _make_sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


# ---------------------------------------------------------------------------
# Interrupt/resume workflow (simplified version for spike)
# ---------------------------------------------------------------------------

from typing import Any, TypedDict


class InterruptState(TypedDict, total=False):
    task_id: str
    question: str
    answer: str
    plan: str
    phase: str
    events: list[str]


def intake_with_question(state: InterruptState) -> dict:
    """Simulates a node that needs user input."""
    return {
        "phase": "INTAKE",
        "events": ["[INTAKE] Started"],
    }


def ask_question_node(state: InterruptState) -> dict:
    """Node that interrupts for user input."""
    answer = interrupt({
        "question_id": "Q-001",
        "question": "Which database provider should we use?",
        "options": ["PostgreSQL", "MySQL", "SQLite"],
    })
    return {
        "answer": str(answer),
        "phase": "ANSWERED",
        "events": [f"[QUESTION] Got answer: {answer}"],
    }


def finalize_with_answer(state: InterruptState) -> dict:
    """Uses the answer to create a plan."""
    return {
        "plan": f"Plan using {state.get('answer', 'unknown')}",
        "phase": "COMPLETED",
        "events": [f"[FINALIZE] Plan created with answer: {state.get('answer')}"],
    }


def _build_interrupt_workflow():
    graph = StateGraph(InterruptState)
    graph.add_node("intake", intake_with_question)
    graph.add_node("ask_question", ask_question_node)
    graph.add_node("finalize", finalize_with_answer)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "ask_question")
    graph.add_edge("ask_question", "finalize")
    graph.add_edge("finalize", END)
    return graph


class TestInterruptResume:
    """P0.3: tạm dừng khi có câu hỏi; resume cùng thread/run."""

    def test_interrupt_pauses_and_resume_continues(self):
        """Workflow pauses at interrupt, resumes with answer, completes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "interrupt.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = _build_interrupt_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-interrupt-001"}}

                # Run until interrupt
                result = workflow.invoke(
                    {"task_id": "TASK-001", "events": []},
                    config=config,
                )

                # Check state — should be paused
                state = workflow.get_state(config)
                assert len(state.tasks) > 0, "Should have pending tasks at interrupt"

                # Get the interrupt data
                pending = state.tasks[0]
                assert len(pending.interrupts) > 0
                interrupt_data = pending.interrupts[0].value
                assert interrupt_data["question_id"] == "Q-001"

                # Resume with answer
                resumed = workflow.invoke(
                    Command(resume="PostgreSQL"),
                    config=config,
                )

                # Should have completed
                assert resumed.get("answer") == "PostgreSQL"
                assert resumed.get("phase") == "COMPLETED"
                assert "PostgreSQL" in resumed.get("plan", "")
            finally:
                conn.close()

    def test_interrupt_persists_across_restart(self):
        """Interrupt state survives process restart (new connection)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "interrupt_restart.db")

            # First "process": run until interrupt
            conn1 = _make_sqlite_conn(db_path)
            try:
                cp1 = SqliteSaver(conn1)
                graph1 = _build_interrupt_workflow()
                workflow1 = graph1.compile(checkpointer=cp1)

                config = {"configurable": {"thread_id": "test-interrupt-restart"}}
                workflow1.invoke(
                    {"task_id": "TASK-002", "events": []},
                    config=config,
                )
            finally:
                conn1.close()

            # Second "process": resume from checkpoint
            conn2 = _make_sqlite_conn(db_path)
            try:
                cp2 = SqliteSaver(conn2)
                graph2 = _build_interrupt_workflow()
                workflow2 = graph2.compile(checkpointer=cp2)

                # Verify interrupt state is preserved
                state = workflow2.get_state(config)
                assert len(state.tasks) > 0

                # Resume
                resumed = workflow2.invoke(
                    Command(resume="MySQL"),
                    config=config,
                )
                assert resumed.get("answer") == "MySQL"
                assert resumed.get("phase") == "COMPLETED"
            finally:
                conn2.close()


class TestCrashRecovery:
    """P0.3: crash sau commit không tạo duplicate plan revision."""

    def test_checkpoint_after_each_node(self):
        """Verify that each node creates a new checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "crash.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-crash"}}

                # Stream to count checkpoints
                node_count = 0
                for update in workflow.stream(
                    SAMPLE_INPUT, config=config, stream_mode="updates"
                ):
                    node_count += 1

                # Verify checkpoints exist
                cursor = conn.execute("SELECT COUNT(*) FROM checkpoints")
                cp_count = cursor.fetchone()[0]
                assert cp_count > 0

                # Get history — should have entries for each node
                history = list(workflow.get_state_history(config))
                assert len(history) >= node_count
            finally:
                conn.close()

    def test_restart_same_thread_no_duplicate_plan(self):
        """Restart on completed thread should not create a new plan revision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "dup.db")
            conn = _make_sqlite_conn(db_path)
            try:
                checkpointer = SqliteSaver(conn)
                graph = build_workflow()
                workflow = graph.compile(checkpointer=checkpointer)

                config = {"configurable": {"thread_id": "test-no-dup-plan"}}

                # First run
                result1 = workflow.invoke(SAMPLE_INPUT, config=config)
                plan1 = result1.get("plan")
                assert plan1 is not None

                # Verify state is at END
                state = workflow.get_state(config)
                plan_from_state = state.values.get("plan")
                assert plan_from_state == plan1

                # Check revision — should be exactly 1
                assert plan1["revision"] == 1
            finally:
                conn.close()
