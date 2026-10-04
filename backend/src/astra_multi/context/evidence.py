from __future__ import annotations

import json

from pydantic import JsonValue, TypeAdapter

from astra_multi.context.snapshots import digest
from astra_multi.domain.commands import AddRecord, Record
from astra_multi.domain.models import (
    Claim,
    Evidence,
    Lease,
    ToolCall,
    ValidationResult,
    ValidationStatus,
)
from astra_multi.domain.repositories import ArtifactStore, RunRepository
from astra_multi.sandbox.runner import JobResult
from astra_multi.tools.contracts import ToolResult


class EvidenceLedger:
    def __init__(
        self, repository: RunRepository, artifacts: ArtifactStore, lease: Lease,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.lease = lease

    def add(self, record: Record) -> None:
        state = self.repository.load(self.lease.run_id)
        if record.run_id != state.run.id:
            raise ValueError("record belongs to another run")
        existing = [
            *state.tool_calls, *state.evidence, *state.claims, *state.validations,
        ]
        for item in existing:
            if item.id == record.id:
                if item != record:
                    raise ValueError("record ID already has different content")
                return
        self.repository.commit(state.run.id, AddRecord(
            expected_revision=state.run.revision, node="P2",
            logical_operation_id=f"record-{record.id}", actor="P2-service",
            record=record,
        ), self.lease)

    def record(self, result: ToolResult) -> Evidence:
        result = ToolResult.model_validate(result.model_dump())
        state = self.repository.load(self.lease.run_id)
        if (
            result.request.run_id != state.run.id
            or result.request.snapshot_id != state.run.snapshot_id
            or result.output_ref.content_hash != result.content_hash
            or result.request_hash != digest(result.request.model_dump_json().encode())
        ):
            raise ValueError("tool result provenance mismatch")
        if result.source_type == "repo":
            if state.snapshot is None:
                raise ValueError("repository evidence requires a snapshot")
            prefix = f"snapshot://{state.snapshot.id}/"
            if not result.locator.startswith(prefix):
                raise ValueError("result locator is outside snapshot")
            for source in result.sources:
                path = source.locator.removeprefix(prefix)
                if (
                    source.snapshot_id != state.snapshot.id
                    or not source.locator.startswith(prefix)
                    or state.snapshot.file_hashes.get(path) != source.content_hash
                ):
                    raise ValueError("source hash/locator is outside snapshot")
        self.artifacts.read(result.output_ref)
        arguments = TypeAdapter(dict[str, JsonValue]).validate_python({
            "request": result.request.model_dump(mode="json"),
            "sources": [s.model_dump(mode="json") for s in result.sources],
            "page": result.page.model_dump(mode="json"),
            "next_match": result.next_match,
        })
        call = ToolCall(
            id=result.request.call_id, run_id=state.run.id,
            created_at=result.captured_at,
            request_hash=result.request_hash,
            arguments_redacted=arguments,
            environment="snapshot-reader" if result.source_type == "repo" else "scoped-http",
            snapshot_id=state.run.snapshot_id, exit_code=0,
            output_artifact=result.output_ref, started_at=result.captured_at,
            finished_at=result.captured_at,
        )
        self.add(call)
        evidence = Evidence(
            id=f"EVID-{call.id}", run_id=state.run.id,
            created_at=result.captured_at,
            source_type=result.source_type, locator=result.locator,
            content_hash=result.content_hash, captured_at=result.captured_at,
            snapshot_id=state.run.snapshot_id, tool_call_id=call.id,
            status=ValidationStatus.NOT_RUN, artifact=result.output_ref,
        )
        self.add(evidence)
        return evidence

    def record_job(self, job: JobResult) -> tuple[Evidence, ValidationResult]:
        job = JobResult.model_validate(job.model_dump())
        state = self.repository.load(self.lease.run_id)
        if job.run_id != state.run.id or job.snapshot_id != state.run.snapshot_id:
            raise ValueError("job belongs to another run/snapshot")
        self.artifacts.read(job.output_ref)
        report = self.artifacts.put(job.model_dump_json().encode())
        arguments = TypeAdapter(dict[str, JsonValue]).validate_python({
            "command": list(job.command_redacted),
            "expected": job.expected, "profile": job.profile.model_dump(mode="json"),
            "job_report": report.model_dump(mode="json"), "status": job.status,
        })
        request_metadata = {
            "run_id": job.run_id, "snapshot_id": job.snapshot_id, "call_id": job.call_id,
            "command": list(job.command_redacted), "expected": job.expected,
            "profile": job.profile.model_dump(mode="json"),
        }
        self.add(ToolCall(
            id=job.call_id, created_at=job.started_at, run_id=state.run.id,
            request_hash=digest(json.dumps(request_metadata, sort_keys=True).encode()),
            arguments_redacted=arguments,
            environment=f"docker/{job.profile.target_os} {job.profile.image} engine={job.environment.engine_version}",
            snapshot_id=job.snapshot_id, exit_code=job.exit_code,
            output_artifact=job.output_ref, started_at=job.started_at,
            finished_at=job.finished_at if job.exit_code is not None else None,
        ))
        evidence = Evidence(
            id=f"EVID-{job.call_id}", created_at=job.started_at, run_id=state.run.id,
            source_type="tool", locator=f"job://{job.job_id}",
            content_hash=report.content_hash, artifact=report, captured_at=job.finished_at,
            snapshot_id=job.snapshot_id, tool_call_id=job.call_id,
            status=job.validation_status,
        )
        self.add(evidence)
        executed = job.validation_status != ValidationStatus.NOT_RUN
        validation = ValidationResult(
            id=f"VALID-{job.call_id}", created_at=job.started_at, run_id=state.run.id,
            status=job.validation_status, expected=job.expected,
            actual=job.actual if executed else None,
            exit_code=job.exit_code if executed else None,
            tool_call_id=job.call_id if executed else None,
            executed_at=job.finished_at if executed else None,
            evidence_ids=[evidence.id],
        )
        self.add(validation)
        return evidence, validation

    def claim(self, text: str, evidence_ids: list[str], claim_id: str) -> Claim:
        state = self.repository.load(self.lease.run_id)
        known = {e.id: e for e in state.evidence}
        if not evidence_ids or any(
            key not in known or known[key].snapshot_id != state.run.snapshot_id
            for key in evidence_ids
        ):
            raise ValueError("facts require evidence from the current snapshot")
        claim = Claim(
            id=claim_id, run_id=state.run.id, text=text, kind="fact",
            snapshot_id=state.run.snapshot_id, evidence_ids=evidence_ids,
        )
        self.add(claim)
        return claim
