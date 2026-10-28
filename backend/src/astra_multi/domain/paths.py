"""Canonical repository-relative path helpers shared by validation and runtime.

Worker-facing paths are always relative to the repository root.  These helpers
reject absolute paths, Windows drive/UNC paths, NUL bytes and ``..`` traversal
before a filesystem operation is attempted.  Runtime resolution (symlinks,
junctions, case) lives in :mod:`astra_multi.execution.paths`.
"""

from __future__ import annotations

import re
import unicodedata

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class PathValidationError(ValueError):
    """Raised when a path is not a safe repository-relative path."""


def normalize_repo_path(raw: str) -> str:
    """Return a normalized POSIX repository-relative path.

    The function is intentionally pure (no filesystem access) so plan
    validation can run without a repository checkout.  It rejects absolute
    paths and any ``..`` component instead of trying to clamp them.
    """
    if not isinstance(raw, str):
        raise PathValidationError("path must be a string")
    if "\x00" in raw:
        raise PathValidationError("path must not contain NUL bytes")

    value = unicodedata.normalize("NFC", raw.strip()).replace("\\", "/")
    if not value:
        raise PathValidationError("path must not be empty")
    if value.startswith("//"):
        raise PathValidationError(f"UNC/absolute paths are not allowed: {raw}")
    if _DRIVE_PREFIX.match(value):
        raise PathValidationError(f"absolute paths are not allowed: {raw}")
    if value.startswith("/"):
        raise PathValidationError(f"absolute paths are not allowed: {raw}")

    parts: list[str] = []
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathValidationError(f"parent traversal is not allowed: {raw}")
        parts.append(part)
    if not parts:
        raise PathValidationError(f"path must identify a file: {raw}")
    return "/".join(parts)


def path_key(raw: str) -> str:
    """Comparison key for ownership and lease checks (case-insensitive)."""
    return normalize_repo_path(raw).casefold()


def is_sensitive_path(raw: str) -> bool:
    """Heuristic used only to request human review, never to grant access."""
    try:
        normalized = normalize_repo_path(raw).casefold()
    except PathValidationError:
        normalized = raw.casefold()
    name = normalized.rsplit("/", 1)[-1]
    sensitive_names = {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "secrets.yaml",
        "secrets.yml",
    }
    sensitive_parts = {
        "auth",
        "authentication",
        "authorization",
        "security",
        "migration",
        "migrations",
        "alembic",
        "schema",
        "secrets",
        "credentials",
    }
    if name in sensitive_names or name.startswith(".env"):
        return True
    return any(part in sensitive_parts for part in normalized.split("/"))
