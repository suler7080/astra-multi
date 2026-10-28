"""Brokered filesystem access for a single worker execution scope."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from astra_multi.domain.models import FileOperation, WorkerExecutionScope
from astra_multi.domain.paths import PathValidationError, path_key

from .errors import DiffScopeViolation, WorkerFileScopeDenied
from .leases import FileLeaseManager
from .paths import RepoPath, canonicalize_repo_path


@dataclass(frozen=True)
class DiffReport:
    changed_files: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    outside_scope: list[str] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.outside_scope


def _is_symlink_entry(entry: tuple[str, str] | None) -> bool:
    return entry is not None and entry[1].startswith("symlink:")


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = path.lstat().st_file_attributes
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _link_digest(path: Path) -> str:
    try:
        return f"symlink:{os.readlink(path)}"
    except OSError:
        return "symlink:!unreadable"


class FileBroker:
    """Mediates every worker file operation through scope and lease checks."""

    def __init__(
        self,
        repository_root: Path,
        scope: WorkerExecutionScope,
        leases: FileLeaseManager,
    ) -> None:
        self.root = repository_root.resolve()
        self.scope = scope
        self.leases = leases
        self.owned_keys = {path_key(path) for path in scope.owned_files}
        self.allowed_operations = set(scope.allowed_operations)

    # -- authorization -------------------------------------------------
    def _canonicalize(self, path: str | Path) -> RepoPath:
        raw = str(path)
        try:
            return canonicalize_repo_path(self.root, raw)
        except PathValidationError as exc:
            raise WorkerFileScopeDenied(
                f"Path is outside repository: {raw}",
                path=raw,
                operation="canonicalize",
                rule="WORKER_FILE_PATH_OUTSIDE_REPO",
            ) from exc

    def _authorize(self, path: str | Path, operation: FileOperation) -> RepoPath:
        raw = str(path)
        canonical = self._canonicalize(path)

        if operation not in self.allowed_operations:
            raise WorkerFileScopeDenied(
                f"Operation {operation.value!r} is not allowed for this worker",
                path=canonical.relative,
                operation=operation.value,
                rule="WORKER_FILE_OPERATION_DENIED",
            )
        if canonical.key not in self.owned_keys:
            raise WorkerFileScopeDenied(
                f"Path is outside worker scope: {raw}",
                path=canonical.relative,
                operation=operation.value,
                rule="WORKER_FILE_PATH_OUTSIDE_SCOPE",
            )

        lease = self.leases.assert_active(
            run_id=self.scope.run_id,
            step_id=self.scope.step_id,
            key=canonical.key,
        )
        if (
            lease.scope_id != self.scope.id
            or lease.worker_role != self.scope.worker_role
        ):
            raise WorkerFileScopeDenied(
                f"File lease for {canonical.relative!r} belongs to a different scope",
                path=canonical.relative,
                operation=operation.value,
                rule="WORKER_FILE_LEASE_SCOPE_MISMATCH",
            )
        conflicts = self.leases.conflicts_for(
            run_id=self.scope.run_id,
            step_id=self.scope.step_id,
            key=canonical.key,
        )
        if conflicts:
            other = conflicts[0]
            raise WorkerFileScopeDenied(
                f"File {canonical.relative!r} is leased by another step "
                f"({other.step_id!r})",
                path=canonical.relative,
                operation=operation.value,
                rule="WORKER_FILE_LEASE_CONFLICT",
            )
        return canonical

    # -- operations ----------------------------------------------------
    def read_file(self, path: str | Path) -> str:
        target = self._authorize(path, FileOperation.READ)
        if not target.absolute.exists() or not target.absolute.is_file():
            raise WorkerFileScopeDenied(
                f"File does not exist: {path}",
                path=target.relative,
                operation=FileOperation.READ.value,
                rule="WORKER_FILE_NOT_FOUND",
            )
        try:
            return target.absolute.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise WorkerFileScopeDenied(
                f"File cannot be read as UTF-8 text: {path}",
                path=target.relative,
                operation=FileOperation.READ.value,
                rule="WORKER_FILE_READ_FAILED",
            ) from exc

    def write_file(self, path: str | Path, content: str) -> None:
        target = self._authorize(path, FileOperation.WRITE)
        if not target.absolute.exists() or not target.absolute.is_file():
            raise WorkerFileScopeDenied(
                f"File does not exist; use create_file: {path}",
                path=target.relative,
                operation=FileOperation.WRITE.value,
                rule="WORKER_FILE_NOT_FOUND",
            )
        try:
            target.absolute.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise WorkerFileScopeDenied(
                f"File cannot be written: {path}",
                path=target.relative,
                operation=FileOperation.WRITE.value,
                rule="WORKER_FILE_WRITE_FAILED",
            ) from exc

    def create_file(self, path: str | Path, content: str) -> None:
        target = self._authorize(path, FileOperation.CREATE)
        if target.absolute.exists():
            raise WorkerFileScopeDenied(
                f"File already exists; use write_file: {path}",
                path=target.relative,
                operation=FileOperation.CREATE.value,
                rule="WORKER_FILE_ALREADY_EXISTS",
            )
        try:
            target.absolute.parent.mkdir(parents=True, exist_ok=True)
            with target.absolute.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise WorkerFileScopeDenied(
                f"File already exists; use write_file: {path}",
                path=target.relative,
                operation=FileOperation.CREATE.value,
                rule="WORKER_FILE_ALREADY_EXISTS",
            ) from exc
        except OSError as exc:
            raise WorkerFileScopeDenied(
                f"File cannot be created: {path}",
                path=target.relative,
                operation=FileOperation.CREATE.value,
                rule="WORKER_FILE_CREATE_FAILED",
            ) from exc

    def delete_file(self, path: str | Path) -> None:
        target = self._authorize(path, FileOperation.DELETE)
        if not target.absolute.exists() or not target.absolute.is_file():
            raise WorkerFileScopeDenied(
                f"File does not exist: {path}",
                path=target.relative,
                operation=FileOperation.DELETE.value,
                rule="WORKER_FILE_NOT_FOUND",
            )
        try:
            target.absolute.unlink()
        except OSError as exc:
            raise WorkerFileScopeDenied(
                f"File cannot be deleted: {path}",
                path=target.relative,
                operation=FileOperation.DELETE.value,
                rule="WORKER_FILE_DELETE_FAILED",
            ) from exc

    # Backwards-compatible aliases.
    def read(self, path: str | Path) -> str:
        return self.read_file(path)

    def write(self, path: str | Path, content: str) -> None:
        target = self._canonicalize(path)
        if target.absolute.exists():
            self.write_file(path, content)
        else:
            self.create_file(path, content)

    # -- post-run verification ----------------------------------------
    def snapshot(self) -> dict[str, str]:
        """Hash every regular file and record every link under the repository.

        Directory links are recorded too and pruned from traversal: a worker
        could otherwise replace an owned parent directory with a link and hide
        all writes behind it from the post-run diff.
        """
        result: dict[str, str] = {}
        for directory, dirnames, filenames in os.walk(
            self.root, topdown=True, followlinks=False
        ):
            dirnames[:] = [name for name in dirnames if name != ".git"]
            for dirname in list(dirnames):
                absolute = Path(directory) / dirname
                if not _is_link(absolute):
                    continue
                try:
                    relative = absolute.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                result[relative] = _link_digest(absolute)
                dirnames.remove(dirname)
            for filename in filenames:
                absolute = Path(directory) / filename
                try:
                    relative = absolute.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                if _is_link(absolute):
                    # Record the link target instead of skipping it so a
                    # worker cannot hide an owned file behind a symlink.
                    result[relative] = _link_digest(absolute)
                    continue
                result[relative] = self._hash(absolute)
        return result

    def verify_diff(self, before: dict[str, str]) -> DiffReport:
        after = self.snapshot()
        before_by_key = {path_key(path): (path, digest) for path, digest in before.items()}
        after_by_key = {path_key(path): (path, digest) for path, digest in after.items()}
        changed: list[str] = []
        created: list[str] = []
        deleted: list[str] = []
        outside: list[str] = []
        in_scope: list[str] = []

        for key in sorted(set(before_by_key) | set(after_by_key)):
            old = before_by_key.get(key)
            new = after_by_key.get(key)
            if old is not None and new is not None and old[1] == new[1]:
                continue
            display = (new or old or (key, ""))[0]
            changed.append(display)
            if old is None:
                created.append(display)
            elif new is None:
                deleted.append(display)
            # A symlink can redirect later reads/writes outside the repository,
            # so a changed or newly created link is never in scope - even when
            # it sits at an owned path.
            if key in self.owned_keys and not _is_symlink_entry(new):
                in_scope.append(display)
            else:
                outside.append(display)

        return DiffReport(
            changed_files=sorted(changed),
            created_files=sorted(created),
            deleted_files=sorted(deleted),
            outside_scope=sorted(outside),
            in_scope=sorted(in_scope),
        )

    def verify_snapshot(self, before: dict[str, str]) -> None:
        report = self.verify_diff(before)
        if not report.passed:
            raise DiffScopeViolation(
                f"Worker changed files outside declared scope: {report.outside_scope}",
                outside_scope=report.outside_scope,
            )

    @staticmethod
    def _hash(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return "!unreadable"
