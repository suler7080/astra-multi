"""Budget tracking, atomic reservations, and reconciliation for model and tool operations.

P3.4 Budget, stop conditions and cancellation:
- Atomic reservations for concurrent calls.
- Reconciles usage (token / cost / call count).
- Retry and output repair fees count towards budget.
- Clean cancellation and pending reservation resolution.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from astra_multi.domain.commands import AddRecord
from astra_multi.domain.models import (
    BudgetReservation,
    Lease,
)
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

    @property
    def total_reserved_tokens(self) -> int:
        with self._lock:
            return sum(
                r.tokens for r in self._reservations.values() if r.status == "reserved"
            )

    @property
    def total_reserved_cost(self) -> float:
        with self._lock:
            return sum(
                r.cost for r in self._reservations.values() if r.status == "reserved"
            )

    def reserve(
        self,
        estimated_tokens: int = 1000,
        estimated_cost: float = 0.01,
        operation_id: str | None = None,
    ) -> str:
        """Atomically reserve budget for a planned model or tool call."""
        op_id = operation_id or f"RES-{uuid.uuid4().hex[:8]}"

        with self._lock:
            active_reserved_tokens = sum(
                r.tokens for r in self._reservations.values() if r.status == "reserved"
            )
            active_reserved_cost = sum(
                r.cost for r in self._reservations.values() if r.status == "reserved"
            )
            # Check call count limit
            active_or_settled_calls = (
                self._settled_calls
                + sum(1 for r in self._reservations.values() if r.status == "reserved")
            )
            if self.call_limit > 0 and active_or_settled_calls >= self.call_limit:
                raise BudgetExhaustedError(
                    f"Call limit ({self.call_limit}) exceeded."
                )

            # Check tokens limit
            projected_tokens = self._used_tokens + active_reserved_tokens + estimated_tokens
            if self.token_limit > 0 and projected_tokens > self.token_limit:
                raise BudgetExhaustedError(
                    f"Token limit ({self.token_limit}) would be exceeded (projected: {projected_tokens})."
                )

            # Check cost limit
            projected_cost = self._used_cost + active_reserved_cost + estimated_cost
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

        # If repo is attached, persist reservation record
        if self.repository and self.lease:
            try:
                state = self.repository.load(self.lease.run_id)
                self.repository.commit(
                    self.lease.run_id,
                    AddRecord(
                        expected_revision=state.run.revision,
                        node="budget",
                        logical_operation_id=f"reserve-{op_id}",
                        actor="budget-service",
                        record=BudgetReservation(
                            id=op_id,
                            run_id=self.lease.run_id,
                            operation_id=op_id,
                            tokens=estimated_tokens,
                            cost=estimated_cost,
                            status="reserved",
                        ),
                    ),
                    self.lease,
                )
            except Exception:
                # If persistence fails, release in-memory reservation and re-raise
                with self._lock:
                    self._reservations.pop(op_id, None)
                raise

        return op_id

    def settle(
        self,
        operation_id: str,
        actual_tokens: int,
        actual_cost: float,
    ) -> None:
        """Settle a reservation with actual usage data."""
        with self._lock:
            res = self._reservations.get(operation_id)
            if not res or res.status != "reserved":
                raise ValueError(f"No active reservation found for operation {operation_id}")

            res.status = "settled"
            self._used_tokens += actual_tokens
            self._used_cost += actual_cost
            self._settled_calls += 1

    def release(self, operation_id: str) -> None:
        """Release reservation without settling (e.g., cancelled or aborted before execution)."""
        with self._lock:
            res = self._reservations.get(operation_id)
            if not res or res.status != "reserved":
                return
            res.status = "released"

    def cancel_all_pending(self) -> None:
        """Mark all active reservations as released upon run cancellation."""
        with self._lock:
            for res in self._reservations.values():
                if res.status == "reserved":
                    res.status = "released"

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used_tokens": self._used_tokens,
                "used_cost": self._used_cost,
                "settled_calls": self._settled_calls,
                "token_limit": self.token_limit,
                "cost_limit": self.cost_limit,
                "call_limit": self.call_limit,
                "active_reservations": sum(
                    1 for r in self._reservations.values() if r.status == "reserved"
                ),
            }
