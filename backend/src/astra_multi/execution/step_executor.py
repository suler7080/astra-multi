"""Run a single plan step under a brokered, leased execution scope.

The executor is the only supported way to give a worker filesystem access.  It
derives the scope from a committed :class:`PlanStep` (never from worker input),
leases every owned file, routes operations through :class:`FileBroker`, and
verifies the post-run diff before returning an audit record.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from astra_multi.domain.models import (
    ExecutionStatus,
    FileOperation,
    PlanStep,
    WorkerExecutionRecord,
    WorkerExecutionScope,
    utc_now,
)

from .errors import (
    DiffScopeViolation,
    FileLeaseConflict,
    StepExecutionDenied,
    StepExecutionError,
    WorkerFileScopeDenied,
)
from .file_broker import DiffReport, FileBroker
from .leases import FileLeaseManager

WorkerCallable = Callable[[FileBroker], None]


@dataclass(frozen=True)
class StepExecutionResult:
    scope: WorkerExecutionScope
    record: WorkerExecutionRecord
    diff: DiffReport


class StepExecutor:
    """Creates scopes, fences files with leases, and audits worker diffs."""

    def __init__(
        self,
        repository_root: Path,
        leases: FileLeaseManager | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        ttl_seconds: int = 900,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("step execution ttl must be positive")
        self.root = repository_root.resolve()
        self.leases = leases or FileLeaseManager(clock=clock, ttl_seconds=ttl_seconds)
        self.clock = clock
        self.ttl_seconds = ttl_seconds

    def create_scope(
        self,
        *,
        run_id: str,
        plan_revision: int,
        step: PlanStep,
        allowed_operations: Sequence[FileOperation] | None = None,
    ) -> WorkerExecutionScope:
        return WorkerExecutionScope.from_plan_step(
            run_id=run_id,
            plan_revision=plan_revision,
            step=step,
            allowed_operations=allowed_operations,
            ttl_seconds=self.ttl_seconds,
            now=self.clock(),
        )

    def execute(
        self,
        *,
        run_id: str,
        plan_revision: int,
        step: PlanStep,
        worker: WorkerCallable,
        allowed_operations: Sequence[FileOperation] | None = None,
    ) -> StepExecutionResult:
        scope = self.create_scope(
            run_id=run_id,
            plan_revision=plan_revision,
            step=step,
            allowed_operations=allowed_operations,
        )
        started_at = scope.created_at
        try:
            self.leases.acquire(
                run_id=run_id,
                scope_id=scope.id,
                step_id=step.id,
                worker_role=scope.worker_role,
                paths=scope.owned_files,
            )
        except FileLeaseConflict as exc:
            record = self._record(
                scope=scope,
                status=ExecutionStatus.DENIED,
                started_at=started_at,
                violations=[f"{exc.rule}: {exc}"],
                diff_passed=False,
            )
            raise StepExecutionDenied(str(exc), record) from exc

        try:
            broker = FileBroker(self.root, scope, self.leases)
            before = broker.snapshot()
            try:
                worker(broker)
            except WorkerFileScopeDenied as exc:
                diff = broker.verify_diff(before)
                record = self._record(
                    scope=scope,
                    status=ExecutionStatus.DENIED,
                    started_at=started_at,
                    diff=diff,
                    violations=[f"{exc.rule}: {exc}"],
                    diff_passed=False,
                )
                raise StepExecutionDenied(str(exc), record) from exc
            except Exception as exc:  # noqa: BLE001 - audit and re-raise below
                diff = broker.verify_diff(before)
                record = self._record(
                    scope=scope,
                    status=ExecutionStatus.FAILED,
                    started_at=started_at,
                    diff=diff,
                    violations=[f"{type(exc).__name__}: {exc}"],
                    diff_passed=False,
                )
                raise StepExecutionError(
                    f"Worker failed while executing step {step.id}: {exc}", record
                ) from exc

            diff = broker.verify_diff(before)
            if not diff.passed:
                record = self._record(
                    scope=scope,
                    status=ExecutionStatus.DENIED,
                    started_at=started_at,
                    diff=diff,
                    violations=[
                        "WORKER_FILE_DIFF_OUT_OF_SCOPE: changed files outside owned scope: "
                        f"{diff.outside_scope}"
                    ],
                    diff_passed=False,
                )
                violation = DiffScopeViolation(
                    "Worker changed files outside declared scope: "
                    f"{diff.outside_scope}",
                    outside_scope=list(diff.outside_scope),
                )
                violation.record = record
                raise violation

            record = self._record(
                scope=scope,
                status=ExecutionStatus.PASSED,
                started_at=started_at,
                diff=diff,
                diff_passed=True,
            )
            return StepExecutionResult(scope=scope, record=record, diff=diff)
        finally:
            self.leases.release(run_id, step.id)

    def _record(
        self,
        *,
        scope: WorkerExecutionScope,
        status: ExecutionStatus,
        started_at: datetime,
        diff: DiffReport | None = None,
        violations: list[str] | None = None,
        diff_passed: bool = True,
    ) -> WorkerExecutionRecord:
        finished_at = max(self.clock(), started_at)
        return WorkerExecutionRecord(
            id=(
                f"EXEC-{scope.run_id}-{scope.step_id}-"
                f"{scope.plan_revision}-{uuid4().hex[:8]}"
            ),
            run_id=scope.run_id,
            plan_revision=scope.plan_revision,
            step_id=scope.step_id,
            scope_id=scope.id,
            worker_role=scope.worker_role,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            diff_passed=diff_passed,
            changed_files=list(diff.changed_files) if diff else [],
            created_files=list(diff.created_files) if diff else [],
            deleted_files=list(diff.deleted_files) if diff else [],
            violations=violations or [],
        )
