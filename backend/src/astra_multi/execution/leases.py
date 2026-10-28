"""Per-file leases for worker execution scopes.

Run-level leases fence whole runs.  File leases are finer-grained: every file a
step intends to touch is leased before the worker starts, and a conflicting
lease held by another step blocks execution.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from astra_multi.domain.models import FileLease, utc_now
from astra_multi.domain.paths import normalize_repo_path, path_key

from .errors import FileLeaseConflict, WorkerFileScopeDenied


class FileLeaseManager:
    """Thread-safe in-memory lease registry with expiry reclamation."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        ttl_seconds: int = 900,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("file lease ttl must be positive")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._leases: dict[tuple[str, str, str], FileLease] = {}

    def acquire(
        self,
        *,
        run_id: str,
        scope_id: str,
        step_id: str,
        worker_role: str,
        paths: Iterable[str],
    ) -> list[FileLease]:
        requested_by_key: dict[str, str] = {}
        for raw_path in paths:
            normalized = normalize_repo_path(raw_path)
            requested_by_key.setdefault(path_key(normalized), normalized)
        requested = list(requested_by_key.values())
        keys = list(requested_by_key)
        if not keys:
            return []
        now = self._clock()
        with self._lock:
            self._reclaim_expired_locked(now)
            conflicts: list[tuple[str, str, str]] = []
            for lease in self._leases.values():
                if (
                    (lease.run_id != run_id or lease.step_id != step_id)
                    and lease.key in keys
                    and lease.expires_at > now
                ):
                    conflicts.append((lease.path, lease.run_id, lease.step_id))
            if conflicts:
                path, other_run, other_step = conflicts[0]
                raise FileLeaseConflict(
                    f"File {path!r} is already leased by run {other_run!r} "
                    f"step {other_step!r}",
                    path=path,
                    operation="lease",
                    conflicting_step=other_step,
                )

            acquired: list[FileLease] = []
            for path, key in zip(requested, keys, strict=True):
                existing = self._leases.get((run_id, step_id, key))
                if existing is not None and existing.expires_at > now:
                    acquired.append(existing)
                    continue
                digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
                lease = FileLease(
                    id=f"LEASE-{step_id}-{digest}",
                    run_id=run_id,
                    scope_id=scope_id,
                    step_id=step_id,
                    worker_role=worker_role,
                    path=path,
                    created_at=now,
                    expires_at=now + timedelta(seconds=self._ttl_seconds),
                )
                self._leases[(run_id, step_id, key)] = lease
                acquired.append(lease)
            return acquired

    def release(self, run_id: str, step_id: str) -> None:
        with self._lock:
            for key in [
                key
                for key in self._leases
                if key[0] == run_id and key[1] == step_id
            ]:
                del self._leases[key]

    def active(self, run_id: str) -> list[FileLease]:
        now = self._clock()
        with self._lock:
            self._reclaim_expired_locked(now)
            return sorted(
                (
                    lease
                    for lease in self._leases.values()
                    if lease.run_id == run_id
                ),
                key=lambda lease: (lease.step_id, lease.path),
            )

    def assert_active(self, *, run_id: str, step_id: str, key: str) -> FileLease:
        now = self._clock()
        with self._lock:
            self._reclaim_expired_locked(now)
            lease = self._leases.get((run_id, step_id, key))
            if lease is None or lease.expires_at <= now:
                raise WorkerFileScopeDenied(
                    f"No active file lease for {key!r} on step {step_id!r}",
                    path=key,
                    operation="lease",
                    rule="WORKER_FILE_LEASE_MISSING",
                )
            return lease

    def conflicts_for(
        self, *, run_id: str, step_id: str, key: str
    ) -> list[FileLease]:
        now = self._clock()
        with self._lock:
            self._reclaim_expired_locked(now)
            return [
                lease
                for lease in self._leases.values()
                if (lease.run_id != run_id or lease.step_id != step_id)
                and lease.key == key
                and lease.expires_at > now
            ]

    def reclaim_expired(self) -> int:
        with self._lock:
            return self._reclaim_expired_locked(self._clock())

    def _reclaim_expired_locked(self, now: datetime) -> int:
        expired = [
            key
            for key, lease in self._leases.items()
            if lease.expires_at <= now
        ]
        for key in expired:
            del self._leases[key]
        return len(expired)
