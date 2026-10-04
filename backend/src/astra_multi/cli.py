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
    state = store.load(args.run_id)
    plan = state.plan
    if not plan:
        print("No plan revision committed yet.")
        return 1

    payload = {
        "run_id": state.run.id,
        "status": state.run.status.value,
        "plan_revision": plan.revision,
        "steps": [s.model_dump(mode="json") for s in plan.steps],
        "decisions": [d.model_dump(mode="json") for d in plan.decisions],
        "risks": plan.risks,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
        else:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
