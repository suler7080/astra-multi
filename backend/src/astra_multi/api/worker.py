"""Background worker and event streaming engine for Astra Multi runs (P5.2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.models import RunStatus
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.budget import BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


class RunWorker:
    """Executes queued runs under lease and coordinates background lifecycle."""

    def __init__(self, store: SQLiteStore, gateway: ModelGateway | None = None) -> None:
        self.store = store
        self.gateway = gateway or ModelGateway(config=GatewayConfig(enable_output_repair=True))
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._run_errors: dict[str, dict[str, Any]] = {}

    def get_run_error(self, run_id: str) -> dict[str, Any] | None:
        """Retrieves cached or persisted error information for a run."""
        if run_id in self._run_errors:
            return self._run_errors[run_id]
        try:
            err_file = self.store.artifacts.root / "errors" / f"{run_id}.log"
            if err_file.exists():
                return {"error": "Execution error", "traceback": err_file.read_text(encoding="utf-8")}
        except Exception:
            pass
        return None

    def start_run(self, run_id: str, max_rounds: int = 2) -> None:
        """Schedules execution of a run in the background."""
        if run_id in self._active_tasks and not self._active_tasks[run_id].done():
            logger.info("Run %s is already running", run_id)
            return

        task = asyncio.create_task(self._execute_run(run_id, max_rounds))
        self._active_tasks[run_id] = task

    async def _execute_run(self, run_id: str, max_rounds: int) -> None:
        """Asynchronously executes the full discussion workflow graph."""
        owner = f"worker-{run_id}"
        lease = None
        try:
            # Acquire lease for execution
            lease = self.store.acquire(run_id, owner=owner, ttl=120)
            controller = WorkflowController(self.store, lease, actor="api-worker")
            context_builder = ContextBuilder(self.store.artifacts)

            # Check budget limits if any
            state = controller.get_state()
            budget_service = None
            if state.run.budget.token_limit or state.run.budget.cost_limit:
                budget_service = BudgetService(
                    token_limit=state.run.budget.token_limit,
                    cost_limit=state.run.budget.cost_limit,
                    repository=self.store,
                    lease=lease,
                )

            active_p = self.store.settings.get_active_provider()
            active_provider_name = active_p["name"] if active_p else None

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=self.gateway,
                context_builder=context_builder,
                budget_service=budget_service,
                provider=active_provider_name,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute graph in worker thread to prevent blocking asyncio loop
            loop = asyncio.get_running_loop()
            initial_state = {
                "run_id": run_id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }

            await loop.run_in_executor(None, app.invoke, initial_state)

        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            logger.exception("Error executing run %s: %s", run_id, exc)
            self._run_errors[run_id] = {
                "error": str(exc),
                "traceback": tb_str,
            }
            try:
                err_dir = self.store.artifacts.root / "errors"
                err_dir.mkdir(parents=True, exist_ok=True)
                (err_dir / f"{run_id}.log").write_text(tb_str, encoding="utf-8")
            except Exception:
                pass
            try:
                # Mark run as FAILED if not already terminal
                state = self.store.load(run_id)
                if state.run.status not in (RunStatus.FINAL, RunStatus.PARTIAL, RunStatus.CANCELLED):
                    if not lease:
                        lease = self.store.acquire(run_id, owner=owner, ttl=30)
                    ctrl = WorkflowController(self.store, lease, actor="api-worker")
                    ctrl.transition_phase(
                        new_phase=state.run.phase,
                        new_status=RunStatus.FAILED,
                        reason=f"Execution error: {exc}",
                    )
            except Exception:
                pass
        finally:
            if lease:
                try:
                    self.store.release(lease)
                except Exception:
                    pass
            self._active_tasks.pop(run_id, None)

    async def shutdown(self) -> None:
        """Cancel and wait for any active background tasks."""
        tasks = list(self._active_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()

    async def event_stream(self, run_id: str, last_event_id: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yields events starting after last_event_id and streams new events until run completes."""
        current_seq = last_event_id
        while True:
            # Fetch events from persistence
            events = self.store.events(run_id, after=current_seq)
            for ev in events:
                current_seq = max(current_seq, ev.sequence)
                yield {
                    "id": ev.sequence,
                    "event": ev.type,
                    "data": {
                        "id": ev.id,
                        "sequence": ev.sequence,
                        "type": ev.type,
                        "actor": ev.actor,
                        "timestamp": ev.timestamp.isoformat(),
                        "payload": ev.payload,
                    },
                }

            # Check if run reached terminal status
            try:
                state = self.store.load(run_id)
                if state.run.status in (RunStatus.FINAL, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED):
                    # Check one last time for any remaining events
                    final_events = self.store.events(run_id, after=current_seq)
                    for ev in final_events:
                        current_seq = max(current_seq, ev.sequence)
                        yield {
                            "id": ev.sequence,
                            "event": ev.type,
                            "data": {
                                "id": ev.id,
                                "sequence": ev.sequence,
                                "type": ev.type,
                                "actor": ev.actor,
                                "timestamp": ev.timestamp.isoformat(),
                                "payload": ev.payload,
                            },
                        }
                    # Send completion event and exit stream
                    yield {
                        "id": current_seq + 1,
                        "event": "run_completed",
                        "data": {
                            "status": state.run.status.value,
                            "phase": state.run.phase.value,
                            "stop_reason": state.run.stop_reason,
                        },
                    }
                    break
            except Exception:
                break

            await asyncio.sleep(0.5)
