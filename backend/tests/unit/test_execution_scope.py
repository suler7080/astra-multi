"""Runtime enforcement tests for worker scopes, file leases and post-run diffs."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from astra_multi.domain.models import (
    ExecutionStatus,
    FileOperation,
    PlanStep,
    RequirementFulfillment,
    WorkerExecutionScope,
)
from astra_multi.domain.paths import PathValidationError, path_key
from astra_multi.execution.errors import (
    DiffScopeViolation,
    FileLeaseConflict,
    StepExecutionDenied,
    WorkerFileScopeDenied,
)
from astra_multi.execution.file_broker import FileBroker
from astra_multi.execution.leases import FileLeaseManager
from astra_multi.execution.paths import canonicalize_repo_path
from astra_multi.execution.step_executor import StepExecutor


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _step(
    *,
    step_id: str = "STEP-001",
    worker_role: str = "worker-a",
    owned_files: list[str] | None = None,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        objective="Implement the owned module",
        requirement_ids=["REQ-001"],
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-001",
                fulfilled_by_section="Implementation",
                concrete_deliverable="A concrete implementation of the module.",
                verification_method="pytest tests/test_module.py",
            )
        ],
        dependencies=[],
        validation="pytest tests/test_module.py",
        deliverables=["module"],
        completion_criteria=["Tests pass"],
        worker_role=worker_role,
        owned_files=owned_files or ["src/api.py"],
    )


def _scope(tmp_path: Path, step: PlanStep) -> WorkerExecutionScope:
    return WorkerExecutionScope.from_plan_step(
        run_id="RUN-001",
        plan_revision=1,
        step=step,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _broker(tmp_path: Path, step: PlanStep) -> tuple[FileBroker, FileLeaseManager]:
    leases = FileLeaseManager()
    scope = _scope(tmp_path, step)
    leases.acquire(
        run_id="RUN-001",
        scope_id=scope.id,
        step_id=step.id,
        worker_role=step.worker_role,
        paths=step.owned_files,
    )
    return FileBroker(tmp_path, scope, leases), leases


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def test_canonical_path_handles_backslashes_and_case(tmp_path: Path):
    target = tmp_path / "src" / "Api.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1", encoding="utf-8")

    resolved = canonicalize_repo_path(tmp_path, "SRC\\API.PY")

    assert resolved.relative.lower() == "src/api.py"
    assert resolved.key == path_key("src/api.py")


def test_canonical_path_rejects_traversal_absolute_and_nul(tmp_path: Path):
    with pytest.raises(PathValidationError, match="traversal"):
        canonicalize_repo_path(tmp_path, "../outside.py")
    with pytest.raises(PathValidationError, match="absolute"):
        canonicalize_repo_path(tmp_path, str(tmp_path / "src" / "api.py"))
    with pytest.raises(PathValidationError, match="NUL"):
        canonicalize_repo_path(tmp_path, "src/\x00api.py")


def test_canonical_path_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(PathValidationError, match="outside repository"):
        canonicalize_repo_path(tmp_path, "link/secret.txt")


@pytest.mark.skipif(os.name != "nt", reason="junction test is Windows-specific")
def test_canonical_path_rejects_junction_escape(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-junction-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")

    with pytest.raises(PathValidationError, match="outside repository"):
        canonicalize_repo_path(tmp_path, "junction/secret.txt")


# ---------------------------------------------------------------------------
# Broker authorization
# ---------------------------------------------------------------------------


def test_broker_allows_owned_file_and_denies_unowned_path(tmp_path: Path):
    broker, _ = _broker(tmp_path, _step())

    broker.create_file("src/api.py", "value = 1")
    assert broker.read_file("src/api.py") == "value = 1"

    with pytest.raises(WorkerFileScopeDenied) as excinfo:
        broker.write_file("src/other.py", "blocked")

    assert excinfo.value.code == "WORKER_FILE_SCOPE_DENIED"
    assert excinfo.value.rule == "WORKER_FILE_PATH_OUTSIDE_SCOPE"
    assert not (tmp_path / "src" / "other.py").exists()


def test_broker_accepts_equivalent_relative_spelling(tmp_path: Path):
    broker, _ = _broker(tmp_path, _step())
    broker.create_file("src/api.py", "value = 1")

    assert broker.read_file("src\\api.py") == "value = 1"
    assert broker.read_file("./src/api.py") == "value = 1"


def test_broker_denies_operation_not_in_scope(tmp_path: Path):
    broker, _ = _broker(tmp_path, _step())
    broker.create_file("src/api.py", "value = 1")
    read_only = FileBroker(
        tmp_path,
        _scope(tmp_path, _step()).model_copy(
            update={"allowed_operations": [FileOperation.READ]}
        ),
        broker.leases,
    )

    assert read_only.read_file("src/api.py") == "value = 1"
    with pytest.raises(WorkerFileScopeDenied) as excinfo:
        read_only.write_file("src/api.py", "changed")

    assert excinfo.value.rule == "WORKER_FILE_OPERATION_DENIED"


def test_broker_denies_write_without_active_lease(tmp_path: Path):
    broker, leases = _broker(tmp_path, _step())
    broker.create_file("src/api.py", "value = 1")
    leases.release("RUN-001", "STEP-001")

    with pytest.raises(WorkerFileScopeDenied) as excinfo:
        broker.write_file("src/api.py", "changed")

    assert excinfo.value.rule == "WORKER_FILE_LEASE_MISSING"


def test_broker_denies_other_step_lease_conflict(tmp_path: Path):
    leases = FileLeaseManager()
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py"],
    )
    step_two = _step(step_id="STEP-002", worker_role="worker-b")
    broker = FileBroker(tmp_path, _scope(tmp_path, step_two), leases)

    with pytest.raises(WorkerFileScopeDenied) as excinfo:
        broker.create_file("src/api.py", "value = 1")

    assert excinfo.value.rule == "WORKER_FILE_LEASE_MISSING"


def test_broker_denies_lease_issued_to_a_different_scope(tmp_path: Path):
    leases = FileLeaseManager()
    step = _step()
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id=step.id,
        worker_role=step.worker_role,
        paths=step.owned_files,
    )
    other_scope = _scope(tmp_path, step).model_copy(
        update={"id": "SCOPE-2", "worker_role": "worker-b"}
    )
    broker = FileBroker(tmp_path, other_scope, leases)

    with pytest.raises(WorkerFileScopeDenied) as excinfo:
        broker.create_file("src/api.py", "value = 1")

    assert excinfo.value.rule == "WORKER_FILE_LEASE_SCOPE_MISMATCH"


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------


def test_lease_conflict_blocks_other_step_and_is_released():
    clock = _Clock()
    leases = FileLeaseManager(clock=clock, ttl_seconds=60)
    first = leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py"],
    )
    same = leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py"],
    )
    assert [lease.id for lease in first] == [lease.id for lease in same]

    with pytest.raises(FileLeaseConflict) as excinfo:
        leases.acquire(
            run_id="RUN-001",
            scope_id="SCOPE-2",
            step_id="STEP-002",
            worker_role="worker-b",
            paths=["src/api.py"],
        )
    assert excinfo.value.rule == "WORKER_FILE_LEASE_CONFLICT"
    assert excinfo.value.conflicting_step == "STEP-001"

    leases.release("RUN-001", "STEP-001")
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-2",
        step_id="STEP-002",
        worker_role="worker-b",
        paths=["src/api.py"],
    )


def test_lease_conflict_blocks_other_run():
    leases = FileLeaseManager()
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py"],
    )

    with pytest.raises(FileLeaseConflict) as excinfo:
        leases.acquire(
            run_id="RUN-002",
            scope_id="SCOPE-2",
            step_id="STEP-001",
            worker_role="worker-b",
            paths=["src/api.py"],
        )

    assert excinfo.value.rule == "WORKER_FILE_LEASE_CONFLICT"
    assert excinfo.value.conflicting_step == "STEP-001"


def test_lease_request_deduplicates_equivalent_paths():
    leases = FileLeaseManager()
    acquired = leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py", "SRC\\API.PY", "./src/api.py"],
    )

    assert len(acquired) == 1
    assert acquired[0].key == path_key("src/api.py")


def test_lease_expiry_is_reclaimed():
    clock = _Clock()
    leases = FileLeaseManager(clock=clock, ttl_seconds=10)
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-1",
        step_id="STEP-001",
        worker_role="worker-a",
        paths=["src/api.py"],
    )

    clock.advance(11)
    assert leases.reclaim_expired() == 1
    assert leases.active("RUN-001") == []
    leases.acquire(
        run_id="RUN-001",
        scope_id="SCOPE-2",
        step_id="STEP-002",
        worker_role="worker-b",
        paths=["src/api.py"],
    )


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------


def test_scope_is_derived_from_plan_step_only(tmp_path: Path):
    step = _step(owned_files=["src/api.py", "tests/test_api.py"])
    executor = StepExecutor(tmp_path)

    scope = executor.create_scope(run_id="RUN-001", plan_revision=1, step=step)

    assert scope.step_id == step.id
    assert scope.worker_role == step.worker_role
    assert scope.owned_files == step.owned_files

    unassigned = _step(worker_role="unassigned")
    with pytest.raises(ValueError, match="unassigned"):
        executor.create_scope(run_id="RUN-001", plan_revision=1, step=unassigned)


def test_executor_records_passing_execution_and_releases_leases(tmp_path: Path):
    executor = StepExecutor(tmp_path)
    step = _step()

    result = executor.execute(
        run_id="RUN-001",
        plan_revision=1,
        step=step,
        worker=lambda broker: broker.create_file("src/api.py", "value = 1"),
    )

    assert result.record.status == ExecutionStatus.PASSED
    assert result.record.diff_passed is True
    assert result.diff.created_files == ["src/api.py"]
    assert result.diff.outside_scope == []
    assert executor.leases.active("RUN-001") == []
    assert (tmp_path / "src" / "api.py").read_text(encoding="utf-8") == "value = 1"


def test_executor_releases_leases_when_snapshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executor = StepExecutor(tmp_path)

    def failing_snapshot(_self: FileBroker) -> dict[str, str]:
        raise OSError("snapshot failed")

    monkeypatch.setattr(FileBroker, "snapshot", failing_snapshot)

    with pytest.raises(OSError, match="snapshot failed"):
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=lambda broker: None,
        )

    assert executor.leases.active("RUN-001") == []


def test_executor_records_each_attempt_with_a_distinct_id(tmp_path: Path):
    executor = StepExecutor(tmp_path)
    step = _step()

    first = executor.execute(
        run_id="RUN-001",
        plan_revision=1,
        step=step,
        worker=lambda broker: broker.create_file("src/api.py", "value = 1"),
    )
    second = executor.execute(
        run_id="RUN-001",
        plan_revision=1,
        step=step,
        worker=lambda broker: broker.write_file("src/api.py", "value = 2"),
    )

    assert first.record.id != second.record.id
    assert first.record.status == second.record.status == ExecutionStatus.PASSED


def test_executor_denies_out_of_scope_broker_operation(tmp_path: Path):
    executor = StepExecutor(tmp_path)

    with pytest.raises(StepExecutionDenied) as excinfo:
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=lambda broker: broker.write_file("src/other.py", "blocked"),
        )

    assert excinfo.value.code == "WORKER_FILE_SCOPE_DENIED"
    assert excinfo.value.record.status == ExecutionStatus.DENIED
    assert excinfo.value.record.diff_passed is False
    assert any(
        "WORKER_FILE_PATH_OUTSIDE_SCOPE" in violation
        for violation in excinfo.value.record.violations
    )
    assert executor.leases.active("RUN-001") == []


def test_executor_rejects_out_of_scope_diff_even_when_broker_bypassed(tmp_path: Path):
    executor = StepExecutor(tmp_path)

    def worker(_broker: FileBroker) -> None:
        (tmp_path / "README.md").write_text("unexpected", encoding="utf-8")

    with pytest.raises(DiffScopeViolation) as excinfo:
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=worker,
        )

    assert excinfo.value.rule == "WORKER_FILE_DIFF_OUT_OF_SCOPE"
    assert excinfo.value.outside_scope == ["README.md"]
    assert excinfo.value.record.status == ExecutionStatus.DENIED
    assert "README.md" in excinfo.value.record.changed_files


def test_executor_rejects_owned_file_replaced_by_symlink(tmp_path: Path):
    owned = tmp_path / "src" / "api.py"
    owned.parent.mkdir(parents=True)
    owned.write_text("value = 1", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-target.txt"
    outside.write_text("outside", encoding="utf-8")
    probe = tmp_path / "symlink-probe"
    try:
        os.symlink(outside, probe)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    probe.unlink()

    executor = StepExecutor(tmp_path)

    def worker(_broker: FileBroker) -> None:
        owned.unlink()
        os.symlink(outside, owned)

    with pytest.raises(DiffScopeViolation) as excinfo:
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=worker,
        )

    assert excinfo.value.outside_scope == ["src/api.py"]
    assert excinfo.value.record.changed_files == ["src/api.py"]
    assert excinfo.value.record.status == ExecutionStatus.DENIED


def test_verify_diff_treats_changed_owned_symlink_as_outside_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    broker, _ = _broker(tmp_path, _step())
    before = {"src/api.py": "old-digest"}
    monkeypatch.setattr(
        broker, "snapshot", lambda: {"src/api.py": "symlink:/outside/target"}
    )

    report = broker.verify_diff(before)

    assert report.outside_scope == ["src/api.py"]
    assert report.in_scope == []
    assert report.passed is False


@pytest.mark.skipif(os.name != "nt", reason="junction test is Windows-specific")
def test_executor_rejects_owned_directory_replaced_by_junction(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-junction-target"
    outside.mkdir()
    (outside / "api.py").write_text("outside", encoding="utf-8")
    probe = tmp_path / "junction-probe"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(probe), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    probe.rmdir()

    executor = StepExecutor(tmp_path)

    def worker(_broker: FileBroker) -> None:
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(tmp_path / "src"), str(outside)],
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr or created.stdout

    with pytest.raises(DiffScopeViolation) as excinfo:
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=worker,
        )

    assert excinfo.value.outside_scope == ["src"]
    assert excinfo.value.record.status == ExecutionStatus.DENIED


def test_executor_rejects_delete_of_unowned_file(tmp_path: Path):
    (tmp_path / "README.md").write_text("keep", encoding="utf-8")
    executor = StepExecutor(tmp_path)

    def worker(_broker: FileBroker) -> None:
        (tmp_path / "README.md").unlink()

    with pytest.raises(DiffScopeViolation) as excinfo:
        executor.execute(
            run_id="RUN-001",
            plan_revision=1,
            step=_step(),
            worker=worker,
        )

    assert excinfo.value.outside_scope == ["README.md"]
    assert excinfo.value.record.deleted_files == ["README.md"]
