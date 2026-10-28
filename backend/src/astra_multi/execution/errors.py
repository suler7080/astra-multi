"""Execution-layer error types."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra_multi.domain.models import WorkerExecutionRecord


class WorkerFileScopeDenied(PermissionError):
    """Blocking denial of a worker file operation.

    The stable ``code`` is part of the public contract: callers and tests assert
    ``WORKER_FILE_SCOPE_DENIED`` instead of parsing prose.
    """

    code = "WORKER_FILE_SCOPE_DENIED"

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        operation: str | None = None,
        rule: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.operation = operation
        self.rule = rule or self.code

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "rule": self.rule,
            "path": self.path,
            "operation": self.operation,
            "message": str(self),
        }


# Backwards-compatible name used by the first iteration of the broker.
FileScopeDenied = WorkerFileScopeDenied


class FileLeaseConflict(WorkerFileScopeDenied):
    """A requested file is already leased by another execution step."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        operation: str | None = None,
        conflicting_step: str | None = None,
    ) -> None:
        super().__init__(
            message,
            path=path,
            operation=operation,
            rule="WORKER_FILE_LEASE_CONFLICT",
        )
        self.conflicting_step = conflicting_step


class DiffScopeViolation(WorkerFileScopeDenied):
    """Post-run diff found changes outside the step's owned files."""

    record: "WorkerExecutionRecord | None" = None

    def __init__(
        self,
        message: str,
        *,
        outside_scope: list[str] | None = None,
    ) -> None:
        super().__init__(message, rule="WORKER_FILE_DIFF_OUT_OF_SCOPE")
        self.outside_scope = outside_scope or []


class StepExecutionDenied(WorkerFileScopeDenied):
    """A step was denied after a record was produced."""

    def __init__(self, message: str, record: "WorkerExecutionRecord") -> None:
        super().__init__(message, rule="WORKER_STEP_EXECUTION_DENIED")
        self.record = record


class StepExecutionError(RuntimeError):
    """A worker raised a non-policy exception; the audit record is attached."""

    def __init__(self, message: str, record: "WorkerExecutionRecord") -> None:
        super().__init__(message)
        self.record = record
