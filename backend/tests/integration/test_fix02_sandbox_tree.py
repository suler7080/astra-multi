"""Tests for FIX-02: WindowsRunner terminates entire child process tree on timeout and cancel."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from astra_multi.context.snapshots import SnapshotStore
from astra_multi.domain.fixtures import sample_state
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.runner import (
    JobRequest,
    SandboxProfile,
    WindowsRunner,
    _terminate_process_tree,
)


def _query_processes_with_marker(marker: str) -> list[dict]:
    """Query living processes containing marker on Windows via Win32_Process."""
    if os.name != "nt":
        return []
    ps_cmd = (
        f"Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.ProcessId -ne $PID -and $_.CommandLine -like '*{marker}*' -and $_.CommandLine -notlike '*Get-CimInstance*' }} | "
        f"Select-Object ProcessId, ParentProcessId, CommandLine | "
        f"ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return [data]
        return data
    except Exception:
        return []


def _kill_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass


@pytest.mark.skipif(os.name != "nt", reason="Windows runner process tree test requires native Windows")
def test_windows_runner_timeout_terminates_child_process_tree(tmp_path: Path):
    """FIX-02: WindowsRunner terminates child processes upon timeout, preventing orphan leaks."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "main.py").write_text("print('hello')", encoding="utf-8")

    db_path = tmp_path / "test.db"
    store = SQLiteStore(db_path)
    try:
        snapshots = SnapshotStore(store.artifacts)
        snapshot = snapshots.capture(repo_dir)
        state = sample_state()
        run = state.run.model_copy(update={"mode": "repo", "snapshot_id": snapshot.snapshot.id})
        store.create(state.task, run, snapshot.snapshot)

        marker = f"FIX02_TIMEOUT_{uuid4().hex[:8]}"
        child_cmd = (
            f"import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '--marker', '{marker}']); "
            f"time.sleep(10)"
        )
        req = JobRequest(
            run_id=run.id,
            snapshot_id=run.snapshot_id,
            call_id="JOB-TIMEOUT-001",
            command=(sys.executable, "-c", child_cmd),
        )

        runner = WindowsRunner(
            snapshots,
            tmp_path / "jobs",
            SandboxProfile(target_os="windows", timeout_seconds=1.5),
        )

        res = runner.execute(snapshot, req)
        assert res.status == "timeout"
        assert res.cleanup_confirmed is True

        # Verify no orphan child processes survive
        time.sleep(1)
        orphans = _query_processes_with_marker(marker)
        if orphans:
            _kill_pids([p["ProcessId"] for p in orphans if "ProcessId" in p])
        assert len(orphans) == 0, f"Found {len(orphans)} leaked orphan child processes: {orphans}"
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows runner process tree test requires native Windows")
def test_windows_runner_cancel_terminates_child_process_tree(tmp_path: Path):
    """FIX-02: WindowsRunner terminates child processes upon cancel signal."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "main.py").write_text("print('hello')", encoding="utf-8")

    db_path = tmp_path / "test.db"
    store = SQLiteStore(db_path)
    try:
        snapshots = SnapshotStore(store.artifacts)
        snapshot = snapshots.capture(repo_dir)
        state = sample_state()
        run = state.run.model_copy(update={"mode": "repo", "snapshot_id": snapshot.snapshot.id})
        store.create(state.task, run, snapshot.snapshot)

        marker = f"FIX02_CANCEL_{uuid4().hex[:8]}"
        child_cmd = (
            f"import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '--marker', '{marker}']); "
            f"time.sleep(10)"
        )
        req = JobRequest(
            run_id=run.id,
            snapshot_id=run.snapshot_id,
            call_id="JOB-CANCEL-001",
            command=(sys.executable, "-c", child_cmd),
        )

        runner = WindowsRunner(
            snapshots,
            tmp_path / "jobs",
            SandboxProfile(target_os="windows", timeout_seconds=15.0),
        )

        cancel_ev = threading.Event()

        def trigger_cancel():
            time.sleep(0.5)
            cancel_ev.set()

        threading.Thread(target=trigger_cancel, daemon=True).start()

        res = runner.execute(snapshot, req, cancel=cancel_ev)
        assert res.status == "cancelled"
        assert res.cleanup_confirmed is True

        # Verify no orphan child processes survive
        time.sleep(1)
        orphans = _query_processes_with_marker(marker)
        if orphans:
            _kill_pids([p["ProcessId"] for p in orphans if "ProcessId" in p])
        assert len(orphans) == 0, f"Found {len(orphans)} leaked orphan child processes: {orphans}"
    finally:
        store.close()


def test_terminate_process_tree_noop_when_exited():
    """_terminate_process_tree is safe and no-op on already terminated processes."""
    p = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    p.wait()
    # Calling terminate helper on exited process must not raise
    _terminate_process_tree(p)
