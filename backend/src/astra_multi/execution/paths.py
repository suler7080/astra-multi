"""Filesystem canonicalization for worker execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from astra_multi.domain.paths import PathValidationError, normalize_repo_path, path_key


@dataclass(frozen=True)
class RepoPath:
    relative: str
    absolute: Path
    key: str


def canonicalize_repo_path(root: Path, raw: str) -> RepoPath:
    """Resolve a worker path and prove it stays inside ``root``.

    ``root`` and every existing symlink/junction on the way are resolved.  A
    path that escapes through ``..``, an absolute prefix, a symlink or a
    junction is rejected even when the textual path looks harmless.
    """
    relative = normalize_repo_path(raw)
    root_resolved = root.resolve()
    candidate = root_resolved / relative
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise PathValidationError(f"path cannot be resolved: {raw}") from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PathValidationError(f"path is outside repository: {raw}") from exc
    # Re-derive the relative path from the resolved target.  This turns
    # equivalent spellings (backslashes, ./ segments, symlinked parents) into
    # one canonical key.
    canonical_relative = resolved.relative_to(root_resolved).as_posix()
    return RepoPath(
        relative=canonical_relative,
        absolute=resolved,
        key=path_key(canonical_relative),
    )
