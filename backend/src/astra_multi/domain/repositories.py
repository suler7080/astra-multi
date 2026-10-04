"""Ports consumed by application services and the checkpoint adapter."""

from typing import Protocol

from .commands import Mutation
from .models import (
    ArtifactRef,
    Event,
    Lease,
    OperationRecord,
    Run,
    RunState,
    Snapshot,
    TaskSpec,
)


class ArtifactStore(Protocol):
    def put(self, content: bytes) -> ArtifactRef: ...
    def read(self, ref: ArtifactRef) -> bytes: ...


class RunRepository(Protocol):
    def create(
        self, task: TaskSpec, run: Run, snapshot: Snapshot | None = None
    ) -> RunState: ...
    def load(self, run_id: str) -> RunState: ...
    def commit(
        self, run_id: str, command: Mutation, lease: Lease
    ) -> OperationRecord: ...
    def events(self, run_id: str, after: int = 0) -> list[Event]: ...
    def operation(
        self, run_id: str, node: str, logical_operation_id: str
    ) -> OperationRecord | None: ...


class LeaseService(Protocol):
    def acquire(self, run_id: str, owner: str, ttl: float = 30) -> Lease: ...
    def heartbeat(self, lease: Lease, ttl: float = 30) -> Lease: ...
    def release(self, lease: Lease) -> None: ...
