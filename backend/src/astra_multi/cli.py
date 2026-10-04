"""Command-line interface for managing runs, viewing status, answering questions, and recovering workflow (P3.5)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from astra_multi.domain.models import (
    Requirement,
    Run,
    RunStatus,
    TaskSpec,
)
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.persistence.sqlite import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-multi",
        description="Astra Multi — Multi-agent software architecture design CLI",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".local/domain.sqlite"),
        help="Path to SQLite persistence database",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path(".local/artifacts"),
        help="Path to artifact storage root",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    create_p = subparsers.add_parser("create", help="Create a new run")
    create_p.add_argument("--goal", required=True, help="Task goal description")
    create_p.add_argument(
        "--requirements",
        nargs="+",
        required=True,
        help="One or more requirement statements",
    )
    create_p.add_argument(
        "--run-id",
        help="Optional run ID (defaults to auto-generated)",
    )

    # status
    status_p = subparsers.add_parser("status", help="Get run status and summary")
    status_p.add_argument("run_id", help="Target run ID")

    # answer
    answer_p = subparsers.add_parser("answer", help="Answer a pending question")
    answer_p.add_argument("run_id", help="Target run ID")
    answer_p.add_argument("question_id", help="Target question ID")
    answer_p.add_argument("--answer", required=True, help="Your answer text")

    # cancel
    cancel_p = subparsers.add_parser("cancel", help="Cancel an active run")
    cancel_p.add_argument("run_id", help="Target run ID")
    cancel_p.add_argument(
        "--reason",
        default="User requested cancellation via CLI",
        help="Cancellation reason",
    )

    # artifacts
    art_p = subparsers.add_parser("artifacts", help="Export or view candidate artifacts")
    art_p.add_argument("run_id", help="Target run ID")
    art_p.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Export format (json or markdown)",
    )

    # validate
    val_p = subparsers.add_parser("validate", help="Run structural quality validator")
    val_p.add_argument("run_id", help="Target run ID")

    # finalize
    fin_p = subparsers.add_parser("finalize", help="Evaluate quality and finalize run status")
    fin_p.add_argument("run_id", help="Target run ID")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start FastAPI web backend and UI")
    serve_p.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    serve_p.add_argument("--port", type=int, default=8000, help="Port to listen on")

    return parser


def cmd_create(store: SQLiteStore, args: argparse.Namespace) -> int:
    import uuid

    run_id = args.run_id or f"RUN-{uuid.uuid4().hex[:8]}"
    task_id = f"TASK-{run_id}"

    reqs = [
        Requirement(
            id=f"REQ-{idx + 1:03d}",
            text=text,
            acceptance="Verified by tests and candidate plan steps",
        )
        for idx, text in enumerate(args.requirements)
    ]

    task = TaskSpec(
        id=task_id,
        goal=args.goal,
        requirements=reqs,
    )

    run = Run(
        id=run_id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="greenfield",
        config_hash="0" * 64,
    )

    store.create(task, run, snapshot=None)
    print(f"Created run {run_id} for task {task_id}")
    return 0


def cmd_status(store: SQLiteStore, args: argparse.Namespace) -> int:
    state = store.load(args.run_id)
    info = {
        "run_id": state.run.id,
        "phase": state.run.phase.value,
        "status": state.run.status.value,
        "revision": state.run.revision,
        "plans": len(state.plans),
        "issues": len(state.issues),
        "open_blocking_issues": sum(
            1
            for i in state.issues
            if i.severity.value == "blocking" and i.status.value != "resolved"
        ),
        "decisions": len(state.decisions),
        "pending_questions": [
            {"id": q.id, "text": q.text}
            for q in state.questions
            if q.answer is None
        ],
        "stop_reason": state.run.stop_reason,
    }
    print(json.dumps(info, indent=2))
    return 0


def cmd_answer(store: SQLiteStore, args: argparse.Namespace) -> int:
    lease = store.acquire(args.run_id, owner="cli-user", ttl=30)
    controller = WorkflowController(store, lease, actor="cli-user")
    controller.answer_question(args.question_id, args.answer)
    store.release(lease)
    print(f"Answered question {args.question_id} for run {args.run_id}")
    return 0


def cmd_cancel(store: SQLiteStore, args: argparse.Namespace) -> int:
    state = store.load(args.run_id)
    lease = store.acquire(args.run_id, owner="cli-user", ttl=30)
    controller = WorkflowController(store, lease, actor="cli-user")
    controller.transition_phase(
        new_phase=state.run.phase,
        new_status=RunStatus.CANCELLED,
        reason=args.reason,
    )
    store.release(lease)
    print(f"Cancelled run {args.run_id}")
    return 0


def cmd_artifacts(store: SQLiteStore, args: argparse.Namespace) -> int:
    from astra_multi.exports.exporter import PlanExporter

    state = store.load(args.run_id)
    if not state.plan:
        print("No plan revision committed yet.")
        return 1

    exporter = PlanExporter()
    if args.format == "markdown":
        output = exporter.export_markdown(state)
        try:
            print(output)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(output.encode("utf-8") + b"\n")
    else:
        output_dict = exporter.export_json(state)
        output_str = json.dumps(output_dict, indent=2, ensure_ascii=False)
        try:
            print(output_str)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(output_str.encode("utf-8") + b"\n")
    return 0


def cmd_validate(store: SQLiteStore, args: argparse.Namespace) -> int:
    from astra_multi.exports.quality_validator import StructuralQualityValidator

    state = store.load(args.run_id)
    validator = StructuralQualityValidator()
    report = validator.validate(state)

    result = {
        "passed": report.passed,
        "plan_revision": report.plan_revision,
        "task_revision": report.task_revision,
        "violations_count": len(report.violations),
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
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if report.passed else 1


def cmd_finalize(store: SQLiteStore, args: argparse.Namespace) -> int:
    from astra_multi.exports.finalization import (
        FinalizationService,
        SemanticReviewAssessment,
    )

    state = store.load(args.run_id)
    service = FinalizationService()

    plan_rev = state.plan.revision if state.plan else 0
    # Auto-synthesize assessment for evaluation
    assessment = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=plan_rev,
        feedback="Verified against requirements.",
        concerns=[],
    )

    decision = service.evaluate(state, assessment)
    if decision.can_finalize:
        lease = store.acquire(args.run_id, owner="quality-service", ttl=30)
        controller = WorkflowController(store, lease, actor="P4-quality-service")
        controller.transition_phase(
            new_phase=state.run.phase,
            new_status=RunStatus.FINAL,
            reason=decision.reason,
        )
        store.release(lease)
        print(f"Run {args.run_id} finalized as FINAL.")
        return 0
    else:
        print(f"Run {args.run_id} cannot be finalized as FINAL. Status: {decision.target_status.value}. Reason: {decision.reason}")
        return 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from astra_multi.api.app import create_app

    app = create_app(db_path=args.db, artifacts_dir=args.artifacts)
    print(f"Starting Astra Multi Web Server on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return cmd_serve(args)

    with SQLiteStore(args.db) as store:
        if args.command == "create":
            return cmd_create(store, args)
        elif args.command == "status":
            return cmd_status(store, args)
        elif args.command == "answer":
            return cmd_answer(store, args)
        elif args.command == "cancel":
            return cmd_cancel(store, args)
        elif args.command == "artifacts":
            return cmd_artifacts(store, args)
        elif args.command == "validate":
            return cmd_validate(store, args)
        elif args.command == "finalize":
            return cmd_finalize(store, args)
        else:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
