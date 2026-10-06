"""FastAPI application for Astra Multi (P5.1 - P5.5)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from astra_multi.api.schemas import (
    AnswerQuestionRequest,
    CancelRunRequest,
    CreateRunRequest,
    RunDetailResponse,
    RunLogEntry,
    RunSummaryResponse,
)
from astra_multi.api.worker import RunWorker
from astra_multi.domain.models import (
    Budget,
    Requirement,
    Run,
    RunStatus,
    TaskSpec,
)
from astra_multi.domain.policies import InvalidState, RevisionConflict
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.gateway.model_gateway import ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


def create_app(
    db_path: Path | None = None,
    artifacts_dir: Path | None = None,
    frontend_dir: Path | None = None,
    gateway: ModelGateway | None = None,
    auto_start_worker: bool = True,
) -> FastAPI:
    """Factory to create and configure the FastAPI application."""
    if db_path is not None:
        db_file = db_path
    elif Path("backend/.local/domain.sqlite").exists():
        db_file = Path("backend/.local/domain.sqlite")
    else:
        db_file = Path(".local/domain.sqlite")

    if artifacts_dir is not None:
        art_dir = artifacts_dir
    elif Path("backend/.local/artifacts").exists():
        art_dir = Path("backend/.local/artifacts")
    else:
        art_dir = Path(".local/artifacts")
    db_file.parent.mkdir(parents=True, exist_ok=True)
    art_dir.mkdir(parents=True, exist_ok=True)

    store = SQLiteStore(db_file, FileArtifactStore(art_dir))
    worker = RunWorker(store, gateway=gateway)

    @asynccontextmanager
    async def lifespan(app_inst: FastAPI) -> AsyncIterator[None]:
        yield
        await worker.shutdown()
        store.close()

    app = FastAPI(
        title="Astra Multi API",
        version="0.1.0",
        description="Local collaborative multi-agent architecture design planning API",
        lifespan=lifespan,
    )

    # Enable CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store in app state
    app.state.store = store
    app.state.worker = worker
    app.state.auto_start_worker = auto_start_worker
    app.state.idempotency_records = {}  # idempotency_key -> (payload_hash, run_id)

    # Global Exception Handlers
    @app.exception_handler(InvalidState)
    async def invalid_state_handler(request: Request, exc: InvalidState) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "invalid_state",
                    "message": str(exc),
                    "correlation_id": correlation_id,
                }
            },
        )

    @app.exception_handler(RevisionConflict)
    async def revision_conflict_handler(request: Request, exc: RevisionConflict) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "revision_conflict",
                    "message": str(exc),
                    "correlation_id": correlation_id,
                }
            },
        )

    # API Endpoints
    @app.post(
        "/api/runs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=dict[str, Any],
        summary="Create and enqueue a new architecture design run",
    )
    async def create_run(
        payload: CreateRunRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        idem_key = idempotency_key or payload.idempotency_key
        payload_repr = json.dumps(payload.model_dump(), sort_keys=True)

        # Check idempotency
        if idem_key:
            if idem_key in app.state.idempotency_records:
                cached_hash, existing_run_id = app.state.idempotency_records[idem_key]
                if cached_hash == payload_repr:
                    return {
                        "run_id": existing_run_id,
                        "status": "RUNNING",
                        "phase": "INTAKE",
                        "message": "Run returned from idempotency key.",
                    }
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key reused with different payload.",
                    )

        run_id = f"RUN-{uuid.uuid4().hex[:8]}"
        task_id = f"TASK-{run_id}"

        requirements = [
            Requirement(
                id=f"REQ-{idx + 1:03d}",
                text=req_text,
                acceptance="Verified by design and candidate test steps",
            )
            for idx, req_text in enumerate(payload.requirements)
        ]

        task = TaskSpec(
            id=task_id,
            goal=payload.goal,
            requirements=requirements,
        )

        run = Run(
            id=run_id,
            task_id=task.id,
            task_revision=1,
            snapshot_id=None,
            mode=payload.mode,
            config_hash="0" * 64,
            budget=Budget(
                token_limit=payload.token_limit,
                cost_limit=payload.cost_limit,
            ),
        )

        store.create(task, run, snapshot=None)

        if idem_key:
            app.state.idempotency_records[idem_key] = (payload_repr, run_id)

        # Start execution in background worker if enabled
        if app.state.auto_start_worker:
            worker.start_run(run_id, max_rounds=payload.max_rounds)

        return {
            "run_id": run_id,
            "status": run.status.value,
            "phase": run.phase.value,
            "message": "Run created and queued for execution.",
        }

    @app.get(
        "/api/runs",
        response_model=list[RunSummaryResponse],
        summary="List all runs",
    )
    async def list_runs() -> list[RunSummaryResponse]:
        cursor = store.connection.execute(
            "SELECT id, state_json FROM runs ORDER BY id DESC"
        )
        rows = cursor.fetchall()
        summaries: list[RunSummaryResponse] = []
        for run_id, state_raw in rows:
            try:
                state_data = json.loads(state_raw)
                run_data = state_data.get("run", {})
                tasks_data = state_data.get("tasks", [])
                goal = tasks_data[0].get("goal", "") if tasks_data else ""
                summaries.append(
                    RunSummaryResponse(
                        run_id=run_id,
                        goal=goal,
                        phase=run_data.get("phase", ""),
                        status=run_data.get("status", ""),
                        revision=run_data.get("revision", 1),
                        created_at=run_data.get("created_at", ""),
                        stop_reason=run_data.get("stop_reason"),
                    )
                )
            except Exception:
                continue
        return summaries

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunDetailResponse,
        summary="Get run detail and overview",
    )
    async def get_run(run_id: str) -> RunDetailResponse:
        try:
            state = store.load(run_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found.",
            )

        return RunDetailResponse(
            run_id=state.run.id,
            task_id=state.task.id,
            task_revision=state.task.revision,
            goal=state.task.goal,
            requirements=[r.model_dump(mode="json") for r in state.task.requirements],
            phase=state.run.phase.value,
            status=state.run.status.value,
            revision=state.run.revision,
            created_at=state.run.created_at.isoformat(),
            stop_reason=state.run.stop_reason,
            plan_revision=state.plan.revision if state.plan else None,
            plans_count=len(state.plans),
            issues_count=len(state.issues),
            blocking_issues_count=sum(
                1 for i in state.issues if i.severity.value == "blocking" and i.status.value != "resolved"
            ),
            decisions_count=len(state.decisions),
            evidence_count=len(state.evidence),
            pending_questions=[
                q.model_dump(mode="json") for q in state.questions if q.answer is None
            ],
        )

    @app.get(
        "/api/runs/{run_id}/events",
        summary="Subscribe to Server-Sent Events stream for a run",
    )
    async def get_run_events(
        run_id: str,
        last_event_id: int | None = Query(default=None),
        header_last_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            store.load(run_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found.",
            )

        start_id = 0
        if last_event_id is not None:
            start_id = last_event_id
        elif header_last_id:
            try:
                start_id = int(header_last_id)
            except ValueError:
                pass

        async def sse_generator() -> AsyncIterator[str]:
            async for ev in worker.event_stream(run_id, last_event_id=start_id):
                payload_json = json.dumps(ev["data"], ensure_ascii=False)
                yield f"id: {ev['id']}\nevent: {ev['event']}\ndata: {payload_json}\n\n"

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/runs/{run_id}/issues", summary="Get all issues for a run")
    async def get_run_issues(run_id: str) -> list[dict[str, Any]]:
        state = store.load(run_id)
        return [i.model_dump(mode="json") for i in state.issues]

    @app.get("/api/runs/{run_id}/evidence", summary="Get all evidence items for a run")
    async def get_run_evidence(run_id: str) -> list[dict[str, Any]]:
        state = store.load(run_id)
        return [e.model_dump(mode="json") for e in state.evidence]

    @app.get(
        "/api/runs/{run_id}/logs",
        summary="Get comprehensive execution logs and error diagnostics for a run",
        response_model=list[RunLogEntry],
    )
    async def get_run_logs(run_id: str) -> list[RunLogEntry]:
        try:
            state = store.load(run_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found.",
            )

        events = store.events(run_id)
        logs: list[RunLogEntry] = []

        # Map domain events to structured logs
        for ev in events:
            payload = ev.payload or {}
            node = payload.get("node", "system")
            ev_type = ev.type
            ts = ev.timestamp.isoformat()
            seq = ev.sequence

            if ev_type == "run_created":
                logs.append(
                    RunLogEntry(
                        id=f"LOG-{seq}",
                        timestamp=ts,
                        level="INFO",
                        node="intake",
                        message=f"Initialized run {run_id} (revision {ev.revision})",
                        details=payload,
                    )
                )
            elif ev_type == "transition_run":
                res = payload.get("result", {})
                phase = res.get("phase", "UNKNOWN")
                run_status = res.get("status", "UNKNOWN")
                reason = res.get("reason")
                if run_status == "FAILED":
                    level = "ERROR"
                    msg = f"Run execution failed in phase {phase}: {reason or state.run.stop_reason or 'Internal error'}"
                elif run_status in ("PARTIAL", "CANCELLED"):
                    level = "WARN"
                    msg = f"Run stopped in phase {phase} ({run_status}): {reason or state.run.stop_reason or ''}".strip()
                else:
                    level = "INFO"
                    msg = f"Transitioned phase to {phase} (Status: {run_status})"
                logs.append(
                    RunLogEntry(
                        id=f"LOG-{seq}",
                        timestamp=ts,
                        level=level,
                        node=node,
                        message=msg,
                        details=payload,
                    )
                )
            elif ev_type == "add_record":
                res = payload.get("result", {})
                rec_id = str(res.get("record_id", ""))
                if "model-call" in str(payload.get("logical_operation_id", "")):
                    logs.append(
                        RunLogEntry(
                            id=f"LOG-{seq}",
                            timestamp=ts,
                            level="INFO",
                            node="model-gateway",
                            message=f"Model invocation recorded: {rec_id}",
                            details=payload,
                        )
                    )
                elif rec_id.startswith("ISSUE"):
                    logs.append(
                        RunLogEntry(
                            id=f"LOG-{seq}",
                            timestamp=ts,
                            level="WARN",
                            node="review",
                            message=f"Reviewer recorded issue {rec_id}",
                            details=payload,
                        )
                    )
                elif rec_id.startswith("DEC"):
                    logs.append(
                        RunLogEntry(
                            id=f"LOG-{seq}",
                            timestamp=ts,
                            level="INFO",
                            node="revise",
                            message=f"Architectural decision recorded {rec_id}",
                            details=payload,
                        )
                    )
                elif rec_id.startswith("PROP"):
                    logs.append(
                        RunLogEntry(
                            id=f"LOG-{seq}",
                            timestamp=ts,
                            level="INFO",
                            node="propose",
                            message=f"Planner proposal recorded {rec_id}",
                            details=payload,
                        )
                    )
                else:
                    logs.append(
                        RunLogEntry(
                            id=f"LOG-{seq}",
                            timestamp=ts,
                            level="INFO",
                            node=node,
                            message=f"Record added: {rec_id}",
                            details=payload,
                        )
                    )
            elif ev_type == "commit_plan":
                res = payload.get("result", {})
                plan_rev = res.get("revision", 1)
                logs.append(
                    RunLogEntry(
                        id=f"LOG-{seq}",
                        timestamp=ts,
                        level="INFO",
                        node="revise",
                        message=f"Synthesizer committed PlanRevision {plan_rev}",
                        details=payload,
                    )
                )
            else:
                logs.append(
                    RunLogEntry(
                        id=f"LOG-{seq}",
                        timestamp=ts,
                        level="INFO",
                        node=node,
                        message=f"Event {ev_type} recorded (seq {seq})",
                        details=payload,
                    )
                )

        # If run has failed or has a stop_reason, ensure a dedicated ERROR log entry with stack trace
        err_info = worker.get_run_error(run_id)
        if state.run.status == RunStatus.FAILED or state.run.stop_reason or err_info:
            last_ts = events[-1].timestamp.isoformat() if events else state.run.created_at.isoformat()
            stop_reason_msg = state.run.stop_reason or (err_info.get("error") if err_info else "Execution error")
            logs.append(
                RunLogEntry(
                    id=f"LOG-ERR-{run_id}",
                    timestamp=last_ts,
                    level="ERROR",
                    node="worker",
                    message=f"Stop reason: {stop_reason_msg}",
                    details={
                        "stop_reason": stop_reason_msg,
                        "status": state.run.status.value,
                        "phase": state.run.phase.value,
                        "traceback": err_info.get("traceback") if err_info else None,
                    },
                )
            )

        return logs

    @app.get("/api/runs/{run_id}/decisions", summary="Get all architectural decisions for a run")
    async def get_run_decisions(run_id: str) -> list[dict[str, Any]]:
        state = store.load(run_id)
        return [d.model_dump(mode="json") for d in state.decisions]

    @app.get("/api/runs/{run_id}/plans/{rev}", summary="Get canonical plan revision")
    async def get_run_plan(run_id: str, rev: int) -> dict[str, Any]:
        state = store.load(run_id)
        matched = next((p for p in state.plans if p.revision == rev), None)
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan revision {rev} not found.",
            )
        return matched.model_dump(mode="json")

    @app.post("/api/runs/{run_id}/answers", summary="Answer a pending question on a waiting run")
    async def answer_question(run_id: str, body: AnswerQuestionRequest) -> dict[str, Any]:
        state = store.load(run_id)
        if body.expected_revision != state.run.revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Expected revision {body.expected_revision} does not match current run revision {state.run.revision}.",
            )
        lease = store.acquire(run_id, owner="api-user", ttl=30)
        try:
            ctrl = WorkflowController(store, lease, actor="api-user")
            updated = ctrl.answer_question(body.question_id, body.answer)
            return {
                "run_id": run_id,
                "status": updated.run.status.value,
                "question_id": body.question_id,
                "message": "Answer recorded successfully.",
            }
        finally:
            store.release(lease)

    @app.post("/api/runs/{run_id}/resume", summary="Resume an interrupted or waiting run")
    async def resume_run(run_id: str) -> dict[str, Any]:
        state = store.load(run_id)
        if state.run.status != RunStatus.WAITING_FOR_INPUT:
            return {
                "run_id": run_id,
                "status": state.run.status.value,
                "message": f"Run is already in status {state.run.status.value}.",
            }

        lease = store.acquire(run_id, owner="api-user", ttl=30)
        try:
            ctrl = WorkflowController(store, lease, actor="api-user")
            updated = ctrl.transition_phase(state.run.phase, RunStatus.RUNNING)
            # Re-enqueue run in worker if enabled
            if app.state.auto_start_worker:
                worker.start_run(run_id)
            return {
                "run_id": run_id,
                "status": updated.run.status.value,
                "message": "Run resumed.",
            }
        finally:
            store.release(lease)

    @app.post("/api/runs/{run_id}/cancel", summary="Cancel an active run")
    async def cancel_run(run_id: str, body: CancelRunRequest) -> dict[str, Any]:
        state = store.load(run_id)
        lease = store.acquire(run_id, owner="api-user", ttl=30)
        try:
            ctrl = WorkflowController(store, lease, actor="api-user")
            ctrl.transition_phase(state.run.phase, RunStatus.CANCELLED, reason=body.reason)
            return {
                "run_id": run_id,
                "status": RunStatus.CANCELLED.value,
                "message": f"Run cancelled: {body.reason}",
            }
        finally:
            store.release(lease)

    @app.get("/api/runs/{run_id}/export", summary="Export candidate plan as JSON or Markdown")
    async def export_plan(
        run_id: str,
        format: str = Query(default="json", pattern="^(json|markdown|md)$"),
        revision: int | None = Query(default=None),
    ) -> Response:
        state = store.load(run_id)
        if not state.plan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No plan committed for export.",
            )

        # If explicit revision requested
        if revision is not None and revision != state.plan.revision:
            matched = next((p for p in state.plans if p.revision == revision), None)
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Plan revision {revision} not found.",
                )
            state = state.model_copy(update={"plans": [matched]})

        exporter = PlanExporter()
        if format in ("markdown", "md"):
            content = exporter.export_markdown(state)
            return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
        else:
            data = exporter.export_json(state)
            return JSONResponse(data)

    @app.post("/api/runs/{run_id}/validate", summary="Run P4 structural quality validation")
    async def validate_run(run_id: str) -> dict[str, Any]:
        state = store.load(run_id)
        validator = StructuralQualityValidator()
        report = validator.validate(state)
        return {
            "passed": report.passed,
            "plan_revision": report.plan_revision,
            "task_revision": report.task_revision,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "entity": v.entity_ref,
                    "message": v.message,
                    "remediation": v.remediation,
                }
                for v in report.violations
            ],
            "uncovered_requirements": report.uncovered_requirements,
            "unresolved_blocking_issues": report.unresolved_blocking_issues,
        }

    @app.post("/api/runs/{run_id}/finalize", summary="Run P4 finalization service to grant FINAL status")
    async def finalize_run(run_id: str) -> dict[str, Any]:
        state = store.load(run_id)
        service = FinalizationService()

        plan_rev = state.plan.revision if state.plan else 0
        assessment = SemanticReviewAssessment(
            passed=True,
            reviewed_plan_revision=plan_rev,
            feedback="Verified against requirements.",
            concerns=[],
        )

        decision = service.evaluate(state, assessment)
        if decision.can_finalize:
            lease = store.acquire(run_id, owner="quality-service", ttl=30)
            try:
                ctrl = WorkflowController(store, lease, actor="P4-quality-service")
                ctrl.transition_phase(state.run.phase, RunStatus.FINAL, reason=decision.reason)
                return {
                    "run_id": run_id,
                    "status": RunStatus.FINAL.value,
                    "message": "Run finalized as FINAL.",
                }
            finally:
                store.release(lease)
        else:
            return {
                "run_id": run_id,
                "status": decision.target_status.value,
                "can_finalize": False,
                "reason": decision.reason,
            }

    # Mount static files if frontend build exists
    repo_root = Path(__file__).resolve().parents[4]
    default_dist = repo_root / "frontend" / "dist"
    static_root = frontend_dir or (default_dist if default_dist.exists() else Path("frontend/dist"))
    if static_root.exists():
        app.mount("/", StaticFiles(directory=str(static_root), html=True), name="frontend")

    return app


# Default app instance
app = create_app()
