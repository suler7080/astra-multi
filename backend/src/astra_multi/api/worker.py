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

# Lease lives longer than any single LLM call chain; heartbeat keeps it alive.
# 300s gives fast crash-takeover while tolerating transient stalls.
LEASE_TTL = 300
HEARTBEAT_INTERVAL = 30
FAILURE_LEASE_TTL = 30


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

    def is_running(self, run_id: str) -> bool:
        """Returns True if a background task for the run is still active."""
        task = self._active_tasks.get(run_id)
        return task is not None and not task.done()

    async def stop_task(self, run_id: str, timeout: float = 5.0) -> None:
        """Cancels the background task for a run and forgets local state."""
        task = self._active_tasks.get(run_id)
        if task is None:
            self._run_errors.pop(run_id, None)
            self._cancellation_events.pop(run_id, None)
            return
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except BaseException:
                pass
        self._active_tasks.pop(run_id, None)
        self._run_errors.pop(run_id, None)
        self._cancellation_events.pop(run_id, None)

    def forget(self, run_id: str) -> None:
        """Drops cached task/error state without cancelling (delete path)."""
        self._active_tasks.pop(run_id, None)
        self._run_errors.pop(run_id, None)
        self._cancellation_events.pop(run_id, None)

    async def _execute_run(self, run_id: str, max_rounds: int) -> None:
        """Asynchronously executes the full discussion workflow graph."""
        owner = f"worker-{run_id}"
        lease = None
        failure_lease = None
        heartbeat_task: asyncio.Task[None] | None = None
        lease_holder: dict[str, Any] = {}
        try:
            # Acquire lease for execution (heartbeat extends it below)
            lease = self.store.acquire(run_id, owner=owner, ttl=LEASE_TTL)
            lease_holder["lease"] = lease
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

            async def _keepalive() -> None:
                """Periodically renew the lease while the graph is running."""
                try:
                    while True:
                        await asyncio.sleep(HEARTBEAT_INTERVAL)
                        try:
                            current = lease_holder.get("lease")
                            if current is None:
                                break
                            renewed = self.store.heartbeat(current, ttl=LEASE_TTL)
                            lease_holder["lease"] = renewed
                            # Propagate renewed lease so later commits/failure
                            # handling use a fresh object (token unchanged,
                            # only expires_at moves; old object still passes
                            # _check_lease, but keep references consistent).
                            try:
                                controller.lease = renewed
                            except Exception:
                                pass
                            if budget_service is not None:
                                try:
                                    budget_service.lease = renewed
                                except Exception:
                                    pass
                        except asyncio.CancelledError:
                            break
                        except Exception as exc_heartbeat:
                            # LeaseLost here means takeover/terminal; stop
                            # heartbeating, graph commit will surface it.
                            logger.warning(
                                "Heartbeat failed for run %s: %s", run_id, exc_heartbeat
                            )
                            break
                except asyncio.CancelledError:
                    pass

            heartbeat_task = asyncio.create_task(_keepalive())

            # Execute graph in worker thread to prevent blocking asyncio loop
            loop = asyncio.get_running_loop()
            initial_state = {
                "run_id": run_id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }

            try:
                await loop.run_in_executor(None, app.invoke, initial_state)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                # Use the latest renewed lease for cleanup / failure marking.
                lease = lease_holder.get("lease", lease)

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
                # Mark run as FAILED if not already terminal.
                # Never reuse a possibly-expired lease: try to acquire a fresh
                # one first, fall back to the last known lease only if takeover
                # is rejected (i.e. current lease is still valid).
                state = self.store.load(run_id)
                if state.run.status not in (RunStatus.FINAL, RunStatus.PARTIAL, RunStatus.CANCELLED):
                    try:
                        failure_lease = self.store.acquire(
                            run_id, owner=owner, ttl=FAILURE_LEASE_TTL
                        )
                    except Exception:
                        failure_lease = lease_holder.get("lease", lease)
                    if failure_lease is None:
                        raise RuntimeError("no lease available to mark run FAILED")
                    ctrl = WorkflowController(
                        self.store, failure_lease, actor="api-worker"
                    )
                    ctrl.transition_phase(
                        new_phase=state.run.phase,
                        new_status=RunStatus.FAILED,
                        reason=f"Execution error: {exc}",
                    )
            except Exception as exc_mark:
                logger.warning("Failed to mark run %s as FAILED: %s", run_id, exc_mark)
        finally:
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    # _execute_run is async; awaiting here is safe except when
                    # the task itself was cancelled — guard anyway.
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                except BaseException:
                    pass
            # Release main lease (latest renewed) and failure lease if distinct.
            if lease:
                try:
                    self.store.release(lease)
                except Exception:
                    pass
            if failure_lease is not None and failure_lease is not lease:
                try:
                    self.store.release(failure_lease)
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
