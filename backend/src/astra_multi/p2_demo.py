"""Capture, inspect, cite and verify a repository without executing it on the host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from astra_multi.context.bundle import ContextBuilder, ContextLimits
from astra_multi.context.evidence import EvidenceLedger
from astra_multi.context.snapshots import SnapshotStore, digest
from astra_multi.domain.models import Requirement, Run, RunPhase, TaskSpec
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.runner import DockerRunner, JobRequest, SandboxProfile
from astra_multi.tools.broker import ToolBroker
from astra_multi.tools.contracts import ToolRequest


def investigate(
    source: Path, workspace: Path, command: tuple[str, ...],
    profile: SandboxProfile = SandboxProfile(),
) -> str:
    source = source.resolve(strict=True)
    workspace = workspace.resolve()
    if workspace.is_relative_to(source):
        raise ValueError("workspace must be outside source repository")
    with SQLiteStore(workspace / "domain.sqlite") as store:
        snapshots = SnapshotStore(store.artifacts)
        snapshot = snapshots.capture(source)
        identity = uuid4().hex
        task = TaskSpec(
            id=f"TASK-{identity}", goal="Inspect repository and verify selected command",
            requirements=[Requirement(
                id="REQ-INSPECT", text="Trace claims to frozen input",
                acceptance="Snapshot, evidence and command results are recoverable",
            )],
        )
        run = Run(
            id=f"RUN-{identity}", task_id=task.id, task_revision=1,
            snapshot_id=snapshot.snapshot.id, mode="repo",
            config_hash=digest(profile.model_dump_json().encode()),
        )
        store.create(task, run, snapshot.snapshot)
        lease = store.acquire(run.id, "P2-demo", ttl=profile.timeout_seconds + 120)
        ledger = EvidenceLedger(store, store.artifacts, lease)
        try:
            broker = ToolBroker(run, snapshots, snapshot)
            listing = broker.execute(ToolRequest(
                run_id=run.id, snapshot_id=run.snapshot_id, call_id="LIST-001", action="list",
            ))
            listed = ledger.record(listing)
            inspection = broker.execute(ToolRequest(
                run_id=run.id, snapshot_id=run.snapshot_id, call_id="INSPECT-001", action="inspect",
            ))
            inspected = ledger.record(inspection)
            ledger.claim(
                f"The frozen snapshot contains {len(snapshot.snapshot.file_hashes)} selected files",
                [listed.id], "CLAIM-001",
            )
            context = ContextBuilder(store.artifacts).build_context(
                store.load(run.id), "planner", RunPhase.INDEPENDENT_ANALYSIS,
                [listed.id, inspected.id], ContextLimits(),
            )
            runner = DockerRunner(snapshots, workspace / "jobs", profile)
            job = runner.execute(snapshot, JobRequest(
                run_id=run.id, snapshot_id=snapshot.snapshot.id,
                call_id="VERIFY-001", command=command,
            ))
            _, validation = ledger.record_job(job)
            report = {
                "run_id": run.id, "snapshot": snapshot.model_dump(mode="json"),
                "context": context.model_dump(mode="json"),
                "job": job.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
                "evidence_index": [
                    item.model_dump(mode="json") for item in store.load(run.id).evidence
                ],
            }
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            artifact = store.artifacts.put(encoded.encode())
            print(f"report artifact: {artifact.content_hash}")
        finally:
            store.release(lease)
    with SQLiteStore(workspace / "domain.sqlite") as reopened:
        reopened.load(run.id)
        reopened.artifacts.read(artifact)
    return encoded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--target-os", choices=["linux", "windows"], default="linux")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    profile = SandboxProfile(target_os="windows" if args.target_os == "windows" else "linux")
    command = tuple(args.command)
    if command and command[0] == "--":
        command = command[1:]
    command = command or ("python", "-m", "unittest", "discover", "-v")
    report = investigate(args.source, args.workspace, command, profile)
    print(report)


if __name__ == "__main__":
    main()
