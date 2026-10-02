import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from astra_multi.context.evidence import EvidenceLedger
from astra_multi.context.snapshots import SnapshotStore
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import ValidationStatus
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.runner import DockerRunner, JobRequest, SandboxProfile


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "repo with spaces"
    root.mkdir()
    (root / "source.txt").write_text("immutable input")
    (root / ".env").write_text("SYNTHETIC_KEY=must_not_mount")
    store = SQLiteStore(tmp_path / "state.sqlite")
    snapshots = SnapshotStore(store.artifacts)
    snapshot = snapshots.capture(root)
    state = sample_state()
    run = state.run.model_copy(update={"mode": "repo", "snapshot_id": snapshot.snapshot.id})
    store.create(state.task, run, snapshot.snapshot)
    lease = store.acquire(run.id, "sandbox-test", ttl=120)
    runner = DockerRunner(snapshots, tmp_path / "jobs")
    try:
        yield runner, snapshot, run, store, EvidenceLedger(store, store.artifacts, lease), root
    finally:
        store.close()


def job_request(run, script, call="JOB-001"):
    return JobRequest(
        run_id=run.id, snapshot_id=run.snapshot_id, call_id=call,
        command=("python", "-c", script),
    )


def require_live(runner):
    if os.environ.get("ASTRA_P2_LIVE_SANDBOX") != "1":
        pytest.skip("NOT_RUN: enable ASTRA_P2_LIVE_SANDBOX=1 for live Docker")
    availability = runner.probe()
    assert availability.available, availability.reason


def test_unavailable_windows_never_executes_host_payload(sandbox):
    runner, snapshot, run, store, ledger, root = sandbox
    unavailable = DockerRunner(
        runner.snapshots, runner.work_root,
        SandboxProfile(target_os="windows"),
    )
    result = unavailable.execute(snapshot, job_request(run, "raise RuntimeError('must not execute')"))
    assert result.status == "unavailable"
    assert result.validation_status == ValidationStatus.NOT_RUN
    evidence, validation = ledger.record_job(result)
    assert validation.status == ValidationStatus.NOT_RUN
    assert validation.actual is None and validation.exit_code is None
    assert evidence.status == ValidationStatus.NOT_RUN
    assert store.load(run.id).tool_calls[0].exit_code is None
    assert (root / "source.txt").read_text() == "immutable input"


def test_missing_image_is_unavailable(sandbox):
    runner, snapshot, run, _, _, _ = sandbox
    missing = DockerRunner(runner.snapshots, runner.work_root, SandboxProfile(
        image="unavailable.invalid/astra@sha256:" + "0" * 64,
    ))
    assert not missing.probe().available
    result = missing.execute(snapshot, job_request(run, "print('never')"))
    assert result.status == "unavailable"


def test_live_redaction_at_output_boundary_and_credential_argv_rejected(sandbox):
    runner, snapshot, run, _, _, _ = sandbox
    require_live(runner)
    redactor = DockerRunner(
        runner.snapshots, runner.work_root, SandboxProfile(output_bytes=256),
        redactions=("immutable input",),
    )
    with pytest.raises(ValueError, match="credentials"):
        redactor.execute(snapshot, job_request(run, "print('immutable input')"))
    result = redactor.execute(snapshot, job_request(
        run, "from pathlib import Path; print('x'*250+Path('source.txt').read_text())",
    ))
    assert result.status == "passed"
    output = runner.snapshots.artifacts.read(result.output_ref)
    assert output == b"x" * 250 + b"[REDAC"
    assert result.output_truncated


@pytest.mark.parametrize("code,status", [(0, "passed"), (3, "failed")])
def test_live_pass_fail_persisted_evidence_and_cleanup(sandbox, code, status):
    runner, snapshot, run, store, ledger, _ = sandbox
    require_live(runner)
    result = runner.execute(snapshot, job_request(run, f"print('evidence'); raise SystemExit({code})"))
    assert result.status == status, result
    assert result.exit_code == code
    assert result.cleanup_confirmed
    evidence, validation = ledger.record_job(result)
    assert validation.status.value == ("PASS" if code == 0 else "FAIL")
    report = json.loads(store.artifacts.read(evidence.artifact))
    assert report["profile"]["image"] == runner.profile.image
    assert store.artifacts.read(result.output_ref) == b"evidence\n"


def test_live_isolation_no_secrets_network_caps_and_copy(sandbox):
    runner, snapshot, run, _, _, root = sandbox
    require_live(runner)
    script = (
        "import os,pathlib,socket; "
        "assert os.geteuid()==65534; "
        "assert 'ASTRA_SENTINEL_SECRET' not in os.environ; "
        "assert not pathlib.Path('/seed/.env').exists(); "
        "assert not pathlib.Path('/var/run/docker.sock').exists(); "
        "assert len(socket.if_nameindex())==1; "
        "assert 'CapEff:\\t0000000000000000' in pathlib.Path('/proc/self/status').read_text(); "
        "assert 'NoNewPrivs:\\t1' in pathlib.Path('/proc/self/status').read_text(); "
        "mount=next(l for l in pathlib.Path('/proc/mounts').read_text().splitlines() if l.split()[1]=='/seed'); "
        "assert 'ro' in mount.split()[3].split(','); "
        "assert pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456'; "
        "assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip()=='64'; "
        "assert pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip()=='100000 100000'; "
        "fs=os.statvfs('/work'); assert fs.f_blocks*fs.f_frsize<=64*1024*1024; "
        "pathlib.Path('source.txt').write_text('job changed copy'); "
        "assert pathlib.Path('/seed/source.txt').read_text()=='immutable input'; "
        "print('isolated')"
    )
    previous = os.environ.get("ASTRA_SENTINEL_SECRET")
    os.environ["ASTRA_SENTINEL_SECRET"] = "synthetic-host-secret"
    try:
        result = runner.execute(snapshot, job_request(run, script))
    finally:
        if previous is None:
            del os.environ["ASTRA_SENTINEL_SECRET"]
        else:
            os.environ["ASTRA_SENTINEL_SECRET"] = previous
    assert result.status == "passed", runner.snapshots.artifacts.read(result.output_ref)
    assert (root / "source.txt").read_text() == "immutable input"
    assert result.profile.network == "none"


def test_live_hang_timeout_and_bounded_large_output(sandbox):
    runner, snapshot, run, _, ledger, _ = sandbox
    require_live(runner)
    bounded = DockerRunner(runner.snapshots, runner.work_root, SandboxProfile(
        timeout_seconds=1, output_bytes=256,
    ))
    result = bounded.execute(snapshot, job_request(
        run, "import time; print('x'*100000,flush=True); time.sleep(60)",
    ))
    assert result.status == "timeout", result
    assert result.validation_status == ValidationStatus.NOT_RUN
    assert result.cleanup_confirmed
    assert result.output_truncated and result.output_ref.size == 256
    assert result.output_total_bytes >= 100000
    _, validation = ledger.record_job(result)
    assert validation.status == ValidationStatus.NOT_RUN
    assert validation.exit_code is None


def test_live_cancel_running_process_tree(sandbox):
    runner, snapshot, run, _, _, _ = sandbox
    require_live(runner)
    cancel, running = threading.Event(), threading.Event()
    script = "import subprocess,time; subprocess.Popen(['python','-c','import time; time.sleep(60)']); time.sleep(60)"
    with ThreadPoolExecutor() as executor:
        future = executor.submit(
            runner.execute, snapshot, job_request(run, script),
            cancel=cancel, on_running=running,
        )
        assert running.wait(timeout=10)
        cancel.set()
        result = future.result(timeout=25)
    assert result.status == "cancelled", result
    assert result.cleanup_confirmed
    assert result.validation_status == ValidationStatus.NOT_RUN
