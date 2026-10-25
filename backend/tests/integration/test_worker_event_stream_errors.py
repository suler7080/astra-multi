"""Tests for FIX-P4 (H-1): SSE stream must surface persistence errors to the client.

Verifies for RunWorker.event_stream:
1. When ``store.events`` raises mid-stream (e.g. SQLite OperationalError, corrupt
   event JSON), the generator logs on the server, yields exactly one terminal
   ``stream_error`` event (with run_id and a short message, no stack trace), and
   terminates cleanly — no hang, no unhandled exception.
2. Same behavior when ``store.get_run_status_info`` raises during polling.
3. Normal terminal completion (flush + ``run_completed``) is unaffected.

Behavior pinned elsewhere and NOT re-tested here:
- A run that does not exist exits silently with zero events
  (tests/integration/test_fix06_sse_lightweight_polling.py).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from astra_multi.api.worker import RunWorker
from astra_multi.domain.commands import TransitionRun
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import RunStatus
from astra_multi.persistence.sqlite import SQLiteStore

SUCCESS_MESSAGE = "Event stream terminated due to an internal error."


def _finalize_run(store: SQLiteStore) -> str:
    """Create a sample run and transition it to FINAL, returning its id."""
    state = sample_state()
    store.create(state.task, state.run)
    lease = store.acquire(state.run.id, owner="worker", ttl=60)
    cmd = TransitionRun(
        expected_revision=state.run.revision,
        node="finalize",
        logical_operation_id="trans-final-p4",
        actor="quality-service",
        phase=state.run.phase,
        status=RunStatus.FINAL,
        reason="Finished",
    )
    store.commit(state.run.id, cmd, lease)
    return state.run.id


@pytest.mark.asyncio
async def test_event_stream_yields_stream_error_when_store_events_fails():
    """store.events failing on a later call ends the stream with one stream_error event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "p4_events_error.db"
        with SQLiteStore(db_path) as store:
            run_id = _finalize_run(store)

            call_count = 0
            orig_events = store.events

            def failing_events(run_id: str, after: int = 0):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    raise RuntimeError("simulated sqlite failure")
                return orig_events(run_id, after=after)

            store.events = failing_events

            worker = RunWorker(store=store)
            collected = []
            async for ev in worker.event_stream(run_id):  # must not raise
                collected.append(ev)

            assert collected, "stream must not end silently on persistence error"

            error_events = [ev for ev in collected if ev["event"] == "stream_error"]
            assert len(error_events) == 1

            replayed = collected[:-1]
            assert replayed, "events already persisted must still be replayed first"
            assert replayed[-1]["id"] < error_events[0]["id"]
            assert not any(ev["event"] == "run_completed" for ev in collected)

            payload = error_events[0]["data"]
            assert payload["run_id"] == run_id
            assert payload["message"] == SUCCESS_MESSAGE


@pytest.mark.asyncio
async def test_event_stream_yields_stream_error_when_status_check_fails():
    """get_run_status_info raising ends the stream with one stream_error event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "p4_status_error.db"
        with SQLiteStore(db_path) as store:
            run_id = _finalize_run(store)

            def failing_status(run_id: str):
                raise RuntimeError("simulated status read failure")

            store.get_run_status_info = failing_status

            worker = RunWorker(store=store)
            collected = []
            async for ev in worker.event_stream(run_id):  # must not raise
                collected.append(ev)

            assert collected, "stream must not end silently on persistence error"
            assert len([ev for ev in collected if ev["event"] == "stream_error"]) == 1

            error_event = collected[-1]
            assert error_event["event"] == "stream_error"
            assert not any(ev["event"] == "run_completed" for ev in collected)
            payload = error_event["data"]
            assert payload["run_id"] == run_id
            assert payload["message"] == SUCCESS_MESSAGE


@pytest.mark.asyncio
async def test_event_stream_normal_completion_unaffected():
    """Happy path keeps its pinned shape: replay then a single terminal run_completed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "p4_normal.db"
        with SQLiteStore(db_path) as store:
            run_id = _finalize_run(store)

            worker = RunWorker(store=store)
            collected = []
            async for ev in worker.event_stream(run_id):
                collected.append(ev)

            assert collected
            assert collected[-1]["event"] == "run_completed"
            assert collected[-1]["data"]["status"] == "FINAL"
            assert collected[-1]["data"]["phase"] == "INTAKE"
            assert collected[-1]["data"]["stop_reason"] == "Finished"
            assert not any(ev["event"] == "stream_error" for ev in collected)
            # Event envelope shape must stay identical to the persisted-event events.
            replayed = collected[0]
            assert set(replayed.keys()) == {"id", "event", "data"}
