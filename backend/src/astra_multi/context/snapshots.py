from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import Field

from astra_multi.domain.models import ArtifactRef, Contract, Snapshot
from astra_multi.domain.repositories import ArtifactStore

DEFAULT_EXCLUDES = (
    ".git", ".env*", "*.pem", "*.key", "credentials*", "secrets*",
    ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".local", "build", "dist",
)


class SnapshotError(ValueError):
    pass


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value or "\\" in value or ":" in value or "\x00" in value
        or path.is_absolute() or ".." in path.parts or str(path) != value
    ):
        raise SnapshotError("path must be a normalized relative POSIX path")
    return value


class SelectionPolicy(Contract):
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    include_untracked: bool = True
    respect_gitignore: bool = True
    max_files: Annotated[int, Field(ge=1)] = 10000
    max_file_bytes: Annotated[int, Field(ge=1)] = 4 * 1024 * 1024
    max_total_bytes: Annotated[int, Field(ge=1)] = 64 * 1024 * 1024


class FileEntry(Contract):
    artifact: ArtifactRef
    executable: bool = False


class Manifest(Contract):
    policy: SelectionPolicy
    files: dict[str, FileEntry]
    excluded: dict[str, str]


class SnapshotRef(Contract):
    snapshot: Snapshot
    manifest: ArtifactRef


Fingerprint = tuple[int, int, int, int, int, str]


class SnapshotStore:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts

    @staticmethod
    def _read(root: Path, path: Path, maximum: int) -> tuple[bytes, os.stat_result, os.stat_result]:
        with ExitStack() as stack:
            if os.name == "posix":
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                directory = os.open(root, flags)
                stack.callback(os.close, directory)
                for part in path.relative_to(root).parts[:-1]:
                    directory = os.open(part, flags, dir_fd=directory)
                    stack.callback(os.close, directory)
                descriptor = os.open(
                    path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
                )
                stream = stack.enter_context(os.fdopen(descriptor, "rb"))
            else:
                stream = stack.enter_context(path.open("rb"))
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise SnapshotError("source changed to a non-regular file")
            content = stream.read(maximum + 1)
            return content, opened, os.fstat(stream.fileno())

    @staticmethod
    def _git(root: Path, *args: str) -> str | None:
        if shutil.which("git") is None:
            return None
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(root), "-c",
                 "core.fsmonitor=false", *args],
                capture_output=True, timeout=10,
            )
            return result.stdout.decode("utf-8", errors="strict") if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, UnicodeError):
            raise SnapshotError("Git metadata timed out or is not UTF-8") from None

    def _scan(
        self, root: Path, policy: SelectionPolicy, selected: set[str] | None,
    ) -> tuple[Manifest, dict[str, Fingerprint]]:
        files: dict[str, FileEntry] = {}
        excluded: dict[str, str] = {}
        fingerprints: dict[str, Fingerprint] = {}
        total = 0
        folded: set[str] = set()

        def visit(directory: Path) -> None:
            nonlocal total
            for path in sorted(directory.iterdir()):
                name = path.relative_to(root).as_posix()
                pattern = next(
                    (p for p in policy.excludes
                     if fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(path.name, p)),
                    None,
                )
                if pattern is not None:
                    excluded[name] = pattern
                    continue
                # Detect symlinks (POSIX) and junctions/reparse points (Windows)
                # On Windows, path.resolve() follows junctions, so check if it differs
                if path.is_symlink() or path.resolve() != path.absolute():
                    excluded[name] = "link/reparse-point"
                    continue
                before = path.stat(follow_symlinks=False)
                if stat.S_ISDIR(before.st_mode):
                    visit(path)
                    continue
                if not stat.S_ISREG(before.st_mode):
                    excluded[name] = "non-regular-file"
                    continue
                if selected is not None and name not in selected:
                    excluded[name] = "git-selection"
                    continue
                safe_path(name)
                if name.casefold() in folded:
                    raise SnapshotError("case-insensitive path collision")
                folded.add(name.casefold())
                if before.st_size > policy.max_file_bytes:
                    raise SnapshotError("file exceeds capture quota")
                content, opened, after = self._read(root, path, policy.max_file_bytes)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise SnapshotError("source changed during open")
                if (
                    (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns, before.st_mode)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns, after.st_mode)
                    or len(content) > policy.max_file_bytes
                    or path.resolve() != path.absolute()
                ):
                    raise SnapshotError("source changed during read")
                total += len(content)
                if total > policy.max_total_bytes or len(files) >= policy.max_files:
                    raise SnapshotError("snapshot exceeds capture quota")
                ref = self.artifacts.put(content)
                files[name] = FileEntry(
                    artifact=ref, executable=bool(before.st_mode & stat.S_IXUSR),
                )
                fingerprints[name] = (
                    before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns, ref.content_hash,
                )

        visit(root)
        return Manifest(policy=policy, files=files, excluded=excluded), fingerprints

    def capture(
        self, root: Path, policy: SelectionPolicy = SelectionPolicy(), *,
        attempts: int = 2, between_scans: Callable[[], None] | None = None,
    ) -> SnapshotRef:
        root = root.resolve(strict=True)
        if not root.is_dir() or not 1 <= attempts <= 5:
            raise SnapshotError("capture requires a directory and 1..5 attempts")
        for _ in range(attempts):
            try:
                commit = self._git(root, "rev-parse", "--verify", "HEAD")
                status = self._git(root, "status", "--porcelain", "-z", "--", ".")
                if status is None and any(
                    (parent / ".git").exists() for parent in (root, *root.parents)
                ):
                    raise SnapshotError("Git metadata unavailable")
                selected = None
                if status is not None:
                    args = ["ls-files", "-z", "--cached"]
                    if policy.include_untracked:
                        args += ["--others"]
                    if policy.respect_gitignore:
                        args += ["--exclude-standard"]
                    listing = self._git(root, *args, "--", ".")
                    if listing is None:
                        raise SnapshotError("Git selection unavailable")
                    selected = set(filter(None, listing.split("\x00")))
                first, fingerprints = self._scan(root, policy, selected)
                if between_scans is not None:
                    between_scans()
                second, verification = self._scan(root, policy, selected)
                if (
                    first != second or fingerprints != verification
                    or status != self._git(root, "status", "--porcelain", "-z", "--", ".")
                    or commit != self._git(root, "rev-parse", "--verify", "HEAD")
                ):
                    raise SnapshotError("source changed during capture")
                encoded = first.model_dump_json().encode()
                manifest = self.artifacts.put(encoded)
                snapshot = Snapshot(
                    id=f"SNAP-{manifest.content_hash}",
                    source_path=str(root),
                    commit_if_any=commit.strip() if commit else None,
                    dirty=bool(status),
                    manifest_hash=manifest.content_hash,
                    file_hashes={p: e.artifact.content_hash for p, e in first.files.items()},
                    excluded_patterns=list(policy.excludes),
                )
                return SnapshotRef(snapshot=snapshot, manifest=manifest)
            except (OSError, SnapshotError) as error:
                failure = error
        raise SnapshotError(f"capture not consistent/available after {attempts} attempts: {failure}")

    def manifest(self, ref: SnapshotRef) -> Manifest:
        content = self.artifacts.read(ref.manifest)
        manifest = Manifest.model_validate_json(content)
        if (
            ref.manifest.content_hash != ref.snapshot.manifest_hash
            or ref.snapshot.id != f"SNAP-{ref.manifest.content_hash}"
            or ref.snapshot.file_hashes != {
                path: entry.artifact.content_hash for path, entry in manifest.files.items()
            }
        ):
            raise SnapshotError("snapshot reference does not match manifest")
        for name in manifest.files:
            safe_path(name)
        return manifest

    def read(self, ref: SnapshotRef, path: str) -> bytes:
        manifest = self.manifest(ref)
        try:
            entry = manifest.files[safe_path(path)]
        except KeyError:
            raise SnapshotError("path is absent from snapshot") from None
        return self.artifacts.read(entry.artifact)

    def materialize(self, ref: SnapshotRef, destination: Path) -> None:
        if destination.exists():
            raise SnapshotError("materialization requires a new directory")
        destination.mkdir(parents=True)
        for name, entry in self.manifest(ref).files.items():
            path = destination / safe_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.artifacts.read(entry.artifact))
            path.chmod(0o755 if entry.executable else 0o644)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
