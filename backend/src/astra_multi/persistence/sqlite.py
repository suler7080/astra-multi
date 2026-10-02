from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from astra_multi.domain.commands import Mutation
from astra_multi.domain.models import (
    TERMINAL,
    Event,
    Lease,
    OperationRecord,
    Run,
    RunPhase,
    RunState,
    RunStatus,
    Snapshot,
    TaskSpec,
    utc_now,
)
from astra_multi.domain.policies import (
    InvalidState,
    LeaseLost,
    OperationConflict,
    RevisionConflict,
    apply_mutation,
)
from astra_multi.domain.repositories import ArtifactStore

from .artifacts import FileArtifactStore
from .migrations import migrate

mutation_adapter: TypeAdapter[Mutation] = TypeAdapter(Mutation)


class SQLiteStore:
    def __init__(
        self,
        database: Path,
        artifacts: ArtifactStore | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = (
            artifacts
            if artifacts is not None
            else FileArtifactStore(database.parent / "artifacts")
        )
        self.clock = clock
        self.fault = fault
        self.connection = sqlite3.connect(database, isolation_level=None, timeout=10)
        try:
            for statement in (
                "PRAGMA foreign_keys=ON",
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=FULL",
            ):
                with closing(self.connection.execute(statement)) as cursor:
                    cursor.fetchall()
            migrate(self.connection)
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def _inject(self, point: str) -> None:
        if self.fault:
            self.fault(point)

    def create(
        self, task: TaskSpec, run: Run, snapshot: Snapshot | None = None
    ) -> RunState:
        state = RunState.model_validate(
            RunState(run=run, tasks=[task], snapshot=snapshot).model_dump()
        )
        if (
            run.revision != 1
            or task.revision != 1
            or run.status != RunStatus.RUNNING
            or run.phase != RunPhase.INTAKE
        ):
            raise InvalidState("new runs must start at revision 1, RUNNING/INTAKE")
        now = self.clock()
        event = Event(
            id=str(uuid4()),
            run_id=run.id,
            sequence=1,
            type="run_created",
            actor="controller",
            revision=1,
            payload={"task_id": task.id},
            timestamp=now,
        )
        with self._transaction():
            self.connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?)",
                (run.id, 1, state.model_dump_json()),
            )
            self.connection.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (run.id, 1, event.model_dump_json()),
            )
        return state

    def load(self, run_id: str) -> RunState:
        row = self.connection.execute(
            "SELECT state_json FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunState.model_validate_json(row[0])

    def operation(
        self, run_id: str, node: str, logical_operation_id: str
    ) -> OperationRecord | None:
        row = self.connection.execute(
            "SELECT operation_json FROM operations WHERE run_id=? AND node=? AND logical_operation_id=?",
            (run_id, node, logical_operation_id),
        ).fetchone()
        return OperationRecord.model_validate_json(row[0]) if row else None

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        rows = self.connection.execute(
            "SELECT event_json FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
            (run_id, after),
        ).fetchall()
        return [Event.model_validate_json(row[0]) for row in rows]

    def _check_artifacts(self, state: RunState) -> None:
        refs = [e.artifact for e in state.evidence]
        refs.extend(t.output_artifact for t in state.tool_calls)
        refs.extend(m.output_artifact for m in state.model_calls)
        for ref in refs:
            if ref:
                self.artifacts.read(ref)

    def commit(self, run_id: str, command: Mutation, lease: Lease) -> OperationRecord:
        command = mutation_adapter.validate_python(command.model_dump())
        request_hash = hashlib.sha256(
            json.dumps(
                command.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with self._transaction():
            self._check_lease(run_id, lease)
            existing = self.operation(
                run_id, command.node, command.logical_operation_id
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise OperationConflict(
                        "operation key already used for a different command"
                    )
                return existing
            state = self.load(run_id)
            updated, result = apply_mutation(state, command, self.clock())
            self._check_artifacts(updated)
            cursor = self.connection.execute(
                "UPDATE runs SET revision=?, state_json=? WHERE id=? AND revision=?",
                (
                    updated.run.revision,
                    updated.model_dump_json(),
                    run_id,
                    command.expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict("concurrent revision update")
            self._inject("after_mutation")
            sequence = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0)+1 FROM events WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
            event = Event(
                id=str(uuid4()),
                run_id=run_id,
                sequence=sequence,
                type=command.kind,
                actor=command.actor,
                revision=updated.run.revision,
                payload={
                    "node": command.node,
                    "logical_operation_id": command.logical_operation_id,
                    "result": result,
                },
                timestamp=self.clock(),
            )
            self.connection.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (run_id, sequence, event.model_dump_json()),
            )
            self._inject("after_event")
            operation = OperationRecord(
                id=str(uuid4()),
                run_id=run_id,
                node=command.node,
                logical_operation_id=command.logical_operation_id,
                request_hash=request_hash,
                revision=updated.run.revision,
                event_sequence=sequence,
                result=result,
            )
            self.connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    command.node,
                    command.logical_operation_id,
                    operation.model_dump_json(),
                ),
            )
            self._inject("after_operation")
            self._check_lease(run_id, lease)
            return operation

    def _check_lease(self, run_id: str, lease: Lease) -> Lease:
        row = self.connection.execute(
            "SELECT owner, token, epoch, expires_at FROM leases WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LeaseLost("run has no lease")
        current = Lease(
            run_id=run_id, owner=row[0], token=row[1], epoch=row[2], expires_at=row[3]
        )
        if (
            lease.run_id != run_id
            or current.token != lease.token
            or current.epoch != lease.epoch
            or current.owner != lease.owner
            or current.expires_at <= self.clock()
        ):
            raise LeaseLost("lease expired or ownership changed")
        return current

    @staticmethod
    def _ttl(ttl: float) -> None:
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl must be finite and positive")

    def acquire(self, run_id: str, owner: str, ttl: float = 30) -> Lease:
        self._ttl(ttl)
        with self._transaction():
            if self.load(run_id).run.status in TERMINAL:
                raise InvalidState("cannot acquire a terminal run")
            now = self.clock()
            row = self.connection.execute(
                "SELECT epoch, expires_at FROM leases WHERE run_id=?", (run_id,)
            ).fetchone()
            if row and datetime.fromisoformat(row[1]) > now:
                raise LeaseLost("run already leased")
            lease = Lease(
                run_id=run_id,
                owner=owner,
                token=str(uuid4()),
                epoch=row[0] + 1 if row else 1,
                expires_at=now + timedelta(seconds=ttl),
            )
            self.connection.execute(
                "INSERT INTO leases VALUES (?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET owner=excluded.owner, token=excluded.token, epoch=excluded.epoch, expires_at=excluded.expires_at",
                (run_id, owner, lease.token, lease.epoch, lease.expires_at.isoformat()),
            )
            return lease

    def heartbeat(self, lease: Lease, ttl: float = 30) -> Lease:
        self._ttl(ttl)
        with self._transaction():
            current = self._check_lease(lease.run_id, lease)
            renewed = Lease.model_validate(
                {
                    **current.model_dump(),
                    "expires_at": self.clock() + timedelta(seconds=ttl),
                }
            )
            self.connection.execute(
                "UPDATE leases SET expires_at=? WHERE run_id=?",
                (renewed.expires_at.isoformat(), lease.run_id),
            )
            return renewed

    def release(self, lease: Lease) -> None:
        with self._transaction():
            self._check_lease(lease.run_id, lease)
            self.connection.execute(
                "UPDATE leases SET expires_at=? WHERE run_id=?",
                (self.clock().isoformat(), lease.run_id),
            )
