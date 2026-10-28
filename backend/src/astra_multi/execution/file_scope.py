"""Backward-compatible facade over the brokered execution layer.

The original ``FileScopeBroker`` accepted a bare path list.  New code must
create a :class:`~astra_multi.domain.models.WorkerExecutionScope` from a
committed plan step and use :class:`~astra_multi.execution.file_broker.FileBroker`
or :class:`~astra_multi.execution.step_executor.StepExecutor`.  This wrapper
keeps the old API working for callers that only need a local scope.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path

from astra_multi.domain.models import FileOperation, WorkerExecutionScope, utc_now

from .errors import FileScopeDenied, WorkerFileScopeDenied
from .file_broker import FileBroker
from .leases import FileLeaseManager

_LEGACY_RUN_ID = "SCOPE-LOCAL"
_LEGACY_STEP_ID = "STEP-LOCAL"


class FileScopeBroker:
    """Restricts file operations to a canonical, declared set of repository paths."""

    def __init__(self, repository_root: Path, owned_files: Iterable[str]) -> None:
        self.root = repository_root.resolve()
        self.owned_files = list(owned_files)
        now = utc_now()
        self.scope = WorkerExecutionScope(
            id=f"SCOPE-{_LEGACY_STEP_ID}",
            run_id=_LEGACY_RUN_ID,
            plan_revision=1,
            step_id=_LEGACY_STEP_ID,
            worker_role="legacy-worker",
            owned_files=self.owned_files,
            allowed_operations=list(FileOperation),
            created_at=now,
            expires_at=now + timedelta(days=365),
        )
        self.leases = FileLeaseManager()
        self.leases.acquire(
            run_id=self.scope.run_id,
            scope_id=self.scope.id,
            step_id=self.scope.step_id,
            worker_role=self.scope.worker_role,
            paths=self.scope.owned_files,
        )
        self._broker = FileBroker(self.root, self.scope, self.leases)

    def read(self, path: str | Path) -> str:
        return self._broker.read(path)

    def write(self, path: str | Path, content: str) -> None:
        self._broker.write(path, content)

    def snapshot(self) -> dict[str, str]:
        return self._broker.snapshot()

    def verify_snapshot(self, before: dict[str, str]) -> None:
        self._broker.verify_snapshot(before)


__all__ = [
    "FileScopeBroker",
    "FileScopeDenied",
    "WorkerFileScopeDenied",
]
