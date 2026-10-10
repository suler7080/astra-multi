"""Budget tracking, atomic reservations, and reconciliation for model and tool operations.

P3.4 Budget, stop conditions and cancellation:
- Atomic reservations for concurrent calls.
- Reconciles usage (token / cost / call count).
- Retry and output repair fees count towards budget.
- Clean cancellation and pending reservation resolution.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from astra_multi.domain.commands import AddRecord
from astra_multi.domain.models import (
    BudgetReservation,
    Lease,
)
from astra_multi.domain.policies import RevisionConflict
from astra_multi.domain.repositories import RunRepository


class BudgetExhaustedError(RuntimeError):
    """Raised when an operation would exceed the configured budget limit."""
    pass


@dataclass
class ReservationRecord:
    operation_id: str
    tokens: int
    cost: float
    status: str = "reserved"  # reserved, settled, released


class BudgetService:
    """Thread-safe budget management service with atomic reservations."""

    def __init__(
        self,
        token_limit: int = 0,
        cost_limit: float = 0.0,
        call_limit: int = 0,
        repository: RunRepository | None = None,
        lease: Lease | None = None,
    ) -> None:
        self.token_limit = token_limit
        self.cost_limit = cost_limit
        self.call_limit = call_limit
        self.repository = repository
        self.lease = lease

        self._lock = threading.Lock()
        self._used_tokens = 0
        self._used_cost = 0.0
        self._settled_calls = 0
        self._reservations: dict[str, ReservationRecord] = {}
        # O(1) in-place tracking counters
        self._reserved_tokens = 0
        self._reserved_cost = 0.0
        self._active_reservations_count = 0

        if self.repository and self.lease:
            self._load_from_repository()

    def _load_from_repository(self) -> None:
        if not (self.repository and self.lease):
            return
        state = self.repository.load(self.lease.run_id)
        with self._lock:
            for r in state.reservations:
                if r.status == "reserved":
                    self._reservations[r.operation_id] = ReservationRecord(
                        operation_id=r.operation_id,
                        tokens=r.tokens,
                        cost=r.cost,
                        status="reserved",
                    )
                    self._reserved_tokens += r.tokens
                    self._reserved_cost += r.cost
                    self._active_reservations_count += 1
                elif r.status == "settled":
                    if r.operation_id in self._reservations:
                        prev = self._reservations[r.operation_id]
                        if prev.status == "reserved":
                            self._reserved_tokens -= prev.tokens
                            self._reserved_cost -= prev.cost
                            self._active_reservations_count -= 1
                        prev.status = "settled"
                        prev.tokens = r.tokens
                        prev.cost = r.cost
                    else:
                        self._reservations[r.operation_id] = ReservationRecord(
                            operation_id=r.operation_id,
                            tokens=r.tokens,
                            cost=r.cost,
                            status="settled",
                        )
                    self._used_tokens += r.tokens
                    self._used_cost += r.cost
                    self._settled_calls += 1
                elif r.status == "released":
                    if r.operation_id in self._reservations:
                        prev = self._reservations[r.operation_id]
                        if prev.status == "reserved":
                            self._reserved_tokens -= prev.tokens
                            self._reserved_cost -= prev.cost
                            self._active_reservations_count -= 1
                        prev.status = "released"
                    else:
                        self._reservations[r.operation_id] = ReservationRecord(
                            operation_id=r.operation_id,
                            tokens=0,
                            cost=0.0,
                            status="released",
                        )
            if abs(self._reserved_cost) < 1e-9:
                self._reserved_cost = 0.0
            if self._reserved_tokens < 0:
                self._reserved_tokens = 0
            if self._active_reservations_count < 0:
                self._active_reservations_count = 0

    def _commit_with_retry(
        self,
        node: str,
        logical_op_id: str,
        record: BudgetReservation,
        max_retries: int = 15,
    ) -> None:
        if not (self.repository and self.lease):
            return

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                state = self.repository.load(self.lease.run_id)
                self.repository.commit(
                    self.lease.run_id,
                    AddRecord(
                        expected_revision=state.run.revision,
                        node=node,
                        logical_operation_id=logical_op_id,
                        actor="budget-service",
                        record=record,
                    ),
                    self.lease,
                )
                return
            except RevisionConflict as err:
                last_err = err
                sleep_time = 0.005 * (2 ** min(attempt, 5)) + random.uniform(0.001, 0.005)
                time.sleep(sleep_time)

        raise RuntimeError(
            f"Failed to commit budget operation '{logical_op_id}' after {max_retries} attempts "
            f"due to revision conflicts: {last_err}"
        ) from last_err

    @property
    def total_reserved_tokens(self) -> int:
        with self._lock:
            return self._reserved_tokens

    @property
    def total_reserved_cost(self) -> float:
        with self._lock:
            return self._reserved_cost

    def reserve(
        self,
        estimated_tokens: int = 1000,
        estimated_cost: float = 0.01,
        operation_id: str | None = None,
    ) -> str:
        """Atomically reserve budget for a planned model or tool call."""
        op_id = operation_id or f"RES-{uuid.uuid4().hex[:8]}"

        with self._lock:
            # Check call count limit in O(1)
            active_or_settled_calls = (
                self._settled_calls + self._active_reservations_count
            )
            if self.call_limit > 0 and active_or_settled_calls >= self.call_limit:
                raise BudgetExhaustedError(
                    f"Call limit ({self.call_limit}) exceeded."
                )

            # Check tokens limit in O(1)
            projected_tokens = self._used_tokens + self._reserved_tokens + estimated_tokens
            if self.token_limit > 0 and projected_tokens > self.token_limit:
                raise BudgetExhaustedError(
                    f"Token limit ({self.token_limit}) would be exceeded (projected: {projected_tokens})."
                )

            # Check cost limit in O(1)
            projected_cost = self._used_cost + self._reserved_cost + estimated_cost
            if self.cost_limit > 0 and projected_cost > self.cost_limit:
                raise BudgetExhaustedError(
                    f"Cost limit (${self.cost_limit:.4f}) would be exceeded (projected: ${projected_cost:.4f})."
                )

            res = ReservationRecord(
                operation_id=op_id,
                tokens=estimated_tokens,
                cost=estimated_cost,
                status="reserved",
            )
            self._reservations[op_id] = res
            self._reserved_tokens += estimated_tokens
            self._reserved_cost += estimated_cost
            self._active_reservations_count += 1

        # If repo is attached, persist reservation record with bounded retry
        if self.repository and self.lease:
            record = BudgetReservation(
                id=op_id,
                run_id=self.lease.run_id,
                operation_id=op_id,
                tokens=estimated_tokens,
                cost=estimated_cost,
                status="reserved",
            )
            try:
                self._commit_with_retry(
                    node="budget",
                    logical_op_id=f"reserve-{op_id}",
                    record=record,
                )
            except Exception:
                # If persistence fails, release in-memory reservation and re-raise
                with self._lock:
                    if op_id in self._reservations and self._reservations[op_id].status == "reserved":
                        self._reservations.pop(op_id, None)
                        self._reserved_tokens -= estimated_tokens
                        self._reserved_cost -= estimated_cost
                        self._active_reservations_count -= 1
                        if abs(self._reserved_cost) < 1e-9:
                            self._reserved_cost = 0.0
                raise

        return op_id

    def settle(
        self,
        operation_id: str,
        actual_tokens: int | None = 0,
        actual_cost: float | None = 0.0,
    ) -> None:
        """Settle a reservation with actual usage data."""
        settle_tokens = int(actual_tokens) if actual_tokens is not None else 0
        settle_cost = float(actual_cost) if actual_cost is not None else 0.0
        with self._lock:
            res = self._reservations.get(operation_id)
            if not res or res.status != "reserved":
                raise ValueError(f"No active reservation found for operation {operation_id}")

            prev_tokens = res.tokens
            prev_cost = res.cost
            res.status = "settled"
            res.tokens = settle_tokens
            res.cost = settle_cost
            self._reserved_tokens -= prev_tokens
            self._reserved_cost -= prev_cost
            self._active_reservations_count -= 1
            if abs(self._reserved_cost) < 1e-9:
                self._reserved_cost = 0.0
            self._used_tokens += settle_tokens
            self._used_cost += settle_cost
            self._settled_calls += 1

        if self.repository and self.lease:
            record = BudgetReservation(
                id=f"settle-{operation_id}",
                run_id=self.lease.run_id,
                operation_id=operation_id,
                tokens=settle_tokens,
                cost=settle_cost,
                status="settled",
            )
            try:
                self._commit_with_retry(
                    node="budget",
                    logical_op_id=f"settle-{operation_id}",
                    record=record,
                )
            except Exception:
                with self._lock:
                    res.status = "reserved"
                    res.tokens = prev_tokens
                    res.cost = prev_cost
                    self._reserved_tokens += prev_tokens
                    self._reserved_cost += prev_cost
                    self._active_reservations_count += 1
                    self._used_tokens -= settle_tokens
                    self._used_cost -= settle_cost
                    self._settled_calls -= 1
                raise

    def release(self, operation_id: str) -> None:
        """Release reservation without settling (e.g., cancelled or aborted before execution)."""
        with self._lock:
            res = self._reservations.get(operation_id)
            if not res or res.status != "reserved":
                return
            prev_tokens = res.tokens
            prev_cost = res.cost
            res.status = "released"
            self._reserved_tokens -= prev_tokens
            self._reserved_cost -= prev_cost
            self._active_reservations_count -= 1
            if abs(self._reserved_cost) < 1e-9:
                self._reserved_cost = 0.0

        if self.repository and self.lease:
            record = BudgetReservation(
                id=f"release-{operation_id}",
                run_id=self.lease.run_id,
                operation_id=operation_id,
                tokens=0,
                cost=0.0,
                status="released",
            )
            try:
                self._commit_with_retry(
                    node="budget",
                    logical_op_id=f"release-{operation_id}",
                    record=record,
                )
            except Exception:
                with self._lock:
                    res.status = "reserved"
                    self._reserved_tokens += prev_tokens
                    self._reserved_cost += prev_cost
                    self._active_reservations_count += 1
                raise

    def cancel_all_pending(self) -> None:
        """Mark all active reservations as released upon run cancellation."""
        with self._lock:
            pending_ids = [
                op_id for op_id, res in self._reservations.items() if res.status == "reserved"
            ]
        for op_id in pending_ids:
            self.release(op_id)

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used_tokens": self._used_tokens,
                "used_cost": self._used_cost,
                "settled_calls": self._settled_calls,
                "token_limit": self.token_limit,
                "cost_limit": self.cost_limit,
                "call_limit": self.call_limit,
                "active_reservations": self._active_reservations_count,
            }
