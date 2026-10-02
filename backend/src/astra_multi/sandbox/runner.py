from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from astra_multi.context.snapshots import SnapshotRef, SnapshotStore
from astra_multi.domain.models import (
    ID,
    UTC,
    ArtifactRef,
    Contract,
    ValidationStatus,
    utc_now,
)

DEFAULT_IMAGE = "python@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb"
BOOTSTRAP = (
    "import os,shutil,sys; "
    "shutil.copytree('/seed','/work/repo'); "
    "os.chdir('/work/repo'); os.execvp(sys.argv[1],sys.argv[1:])"
)


class SandboxProfile(Contract):
    target_os: Literal["linux", "windows"] = "linux"
    image: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[0-9a-f]{64}$")] = DEFAULT_IMAGE
    timeout_seconds: Annotated[float, Field(ge=0.1, le=600, allow_inf_nan=False)] = 15
    memory_mb: Annotated[int, Field(ge=64, le=4096)] = 256
    cpus: Annotated[float, Field(ge=0.1, le=8, allow_inf_nan=False)] = 1
    pids: Annotated[int, Field(ge=8, le=512)] = 64
    workspace_mb: Annotated[int, Field(ge=8, le=1024)] = 64
    output_bytes: Annotated[int, Field(ge=128, le=1024 * 1024)] = 65536
    network: Literal["none"] = "none"


class JobRequest(Contract):
    run_id: ID
    snapshot_id: ID
    call_id: ID
    command: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    expected: str = "command exits with code 0"
    expected_exit: Literal[0] = 0


class Availability(Contract):
    available: bool
    reason: str
    engine_version: str | None = None
    image_id: str | None = None


class JobResult(Contract):
    run_id: ID
    snapshot_id: ID
    call_id: ID
    job_id: ID
    status: Literal["passed", "failed", "timeout", "cancelled", "unavailable"]
    command_redacted: tuple[str, ...]
    expected: str
    actual: str
    exit_code: int | None
    started_at: UTC
    finished_at: UTC
    environment: Availability
    profile: SandboxProfile
    output_ref: ArtifactRef
    output_total_bytes: int
    output_truncated: bool
    cleanup_confirmed: bool

    @model_validator(mode="after")
    def completion(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("job cannot finish before it starts")
        if self.status in {"passed", "failed"}:
            if not self.environment.available or not self.cleanup_confirmed or self.exit_code is None:
                raise ValueError("executed validation requires available runner and confirmed cleanup")
            if (self.status == "passed") != (self.exit_code == 0):
                raise ValueError("validation status does not match exit code")
        return self

    @property
    def validation_status(self) -> ValidationStatus:
        if self.status == "passed":
            return ValidationStatus.PASS
        if self.status == "failed":
            return ValidationStatus.FAIL
        return ValidationStatus.NOT_RUN


class DockerRunner:
    def __init__(
        self, snapshots: SnapshotStore, work_root: Path,
        profile: SandboxProfile = SandboxProfile(), *,
        redactions: tuple[str, ...] = (),
    ) -> None:
        self.snapshots = snapshots
        self.work_root = work_root.resolve()
        if "," in str(self.work_root):
            raise ValueError("Docker mount workspace cannot contain commas")
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.profile = SandboxProfile.model_validate(profile.model_dump())
        self.redactions = tuple(s for s in redactions if s)

    def _redact(self, text: str) -> str:
        for secret in self.redactions:
            text = text.replace(secret, "[REDACTED]")
        return text

    @staticmethod
    def _control(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["docker", *args], capture_output=True, timeout=15,
        )

    def probe(self) -> Availability:
        if self.profile.target_os != "linux":
            return Availability(available=False, reason="native Windows runner not implemented")
        if shutil.which("docker") is None:
            return Availability(available=False, reason="Docker CLI missing")
        try:
            info = self._control("info", "--format", "{{.OSType}}|{{.ServerVersion}}")
            image = self._control("image", "inspect", "--format", "{{.Id}}", self.profile.image)
            if info.returncode != 0 or image.returncode != 0:
                return Availability(available=False, reason="Docker daemon/image unavailable; no automatic pull")
            host, version = info.stdout.decode().strip().split("|", 1)
            if host != "linux":
                return Availability(available=False, reason="Linux container engine required")
            return Availability(
                available=True, reason="Docker Linux/image available",
                engine_version=version, image_id=image.stdout.decode().strip(),
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return Availability(available=False, reason="Docker availability probe failed")

    def execute(
        self, snapshot: SnapshotRef, request: JobRequest, *,
        cancel: threading.Event | None = None,
        on_running: threading.Event | None = None,
    ) -> JobResult:
        request = JobRequest.model_validate(request.model_dump())
        if request.snapshot_id != snapshot.snapshot.id:
            raise ValueError("job snapshot mismatch")
        if any(secret in arg for secret in self.redactions for arg in request.command):
            raise ValueError("credentials are forbidden in command arguments")
        self.snapshots.manifest(snapshot)
        started = utc_now()
        available = self.probe()
        name = f"astra-p2-{uuid4().hex}"
        command = tuple(self._redact(arg) for arg in request.command)
        status: Literal["passed", "failed", "timeout", "cancelled", "unavailable"] = "unavailable"
        reason = available.reason
        output = bytearray()
        total = 0
        exit_code = None
        cleanup = True
        if available.available and not (cancel is not None and cancel.is_set()):
            with tempfile.TemporaryDirectory(prefix="job-", dir=self.work_root) as directory:
                seed = Path(directory) / "seed"
                self.snapshots.materialize(snapshot, seed)
                args = [
                    "create", "--name", name, "--pull=never", "--init",
                    "--network", self.profile.network, "--read-only",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges",
                    "--user=65534:65534", "--pids-limit", str(self.profile.pids),
                    "--memory", f"{self.profile.memory_mb}m",
                    "--memory-swap", f"{self.profile.memory_mb}m",
                    "--cpus", str(self.profile.cpus), "--log-driver=none",
                    "--tmpfs", f"/work:rw,nosuid,nodev,size={self.profile.workspace_mb}m,mode=1777",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
                    "--mount", f"type=bind,src={seed},dst=/seed,readonly",
                    "--workdir=/work", "--entrypoint=python", self.profile.image,
                    "-c", BOOTSTRAP, *request.command,
                ]
                process: subprocess.Popen[bytes] | None = None
                reader: threading.Thread | None = None
                try:
                    created = self._control(*args)
                    if created.returncode != 0:
                        raise ValueError("container could not be created")
                    process = subprocess.Popen(
                        ["docker", "start", "--attach", name],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    )
                    assert process.stdout is not None
                    stream = process.stdout

                    def drain() -> None:
                        nonlocal total
                        while chunk := stream.read(4096):
                            total += len(chunk)
                            redaction_margin = max(
                                (len(s.encode()) for s in self.redactions), default=0,
                            ) + 4
                            remaining = self.profile.output_bytes + redaction_margin - len(output)
                            if remaining > 0:
                                output.extend(chunk[:remaining])

                    reader = threading.Thread(target=drain, daemon=True)
                    reader.start()
                    deadline = time.monotonic() + self.profile.timeout_seconds
                    status = "failed"
                    while process.poll() is None:
                        if on_running is not None and not on_running.is_set():
                            running = self._control("inspect", "--format", "{{.State.Running}}", name)
                            if running.returncode == 0 and running.stdout.strip() == b"true":
                                on_running.set()
                        if cancel is not None and cancel.is_set():
                            status, reason = "cancelled", "job cancelled"
                            break
                        if time.monotonic() >= deadline:
                            status, reason = "timeout", "job exceeded wall-clock limit"
                            break
                        try:
                            process.wait(timeout=0.05)
                        except subprocess.TimeoutExpired:
                            pass
                    if status in {"timeout", "cancelled"}:
                        self._control("kill", name)
                    process.wait(timeout=10)
                    reader.join(timeout=10)
                    state_result = self._control("inspect", "--format", "{{json .State}}", name)
                    state = TypeAdapter(dict[str, JsonValue]).validate_json(state_result.stdout)
                    raw_exit = state.get("ExitCode")
                    if not isinstance(raw_exit, int) or state.get("StartedAt") == "0001-01-01T00:00:00Z":
                        status, reason = "unavailable", "container did not start"
                    else:
                        exit_code = raw_exit
                        if status not in {"timeout", "cancelled"}:
                            status = "passed" if exit_code == request.expected_exit else "failed"
                            reason = f"container exit code {exit_code}"
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    if status not in {"timeout", "cancelled"}:
                        status, reason = "unavailable", "Docker job transport failed"
                finally:
                    try:
                        self._control("rm", "--force", name)
                        remaining = self._control(
                            "ps", "--all", "--filter", f"name=^{name}$", "--format", "{{.Names}}",
                        )
                        cleanup = remaining.returncode == 0 and not remaining.stdout.strip()
                    except (OSError, subprocess.TimeoutExpired):
                        cleanup = False
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=10)
                    if reader is not None:
                        reader.join(timeout=10)
                    if process is not None and process.stdout is not None:
                        process.stdout.close()
        elif cancel is not None and cancel.is_set():
            status, reason = "cancelled", "cancelled before scheduling"
        if not cleanup:
            status, reason = "unavailable", "container cleanup could not be confirmed"
        content = self._redact(bytes(output).decode("utf-8", errors="replace")).encode()[:self.profile.output_bytes]
        return JobResult(
            run_id=request.run_id, snapshot_id=request.snapshot_id, call_id=request.call_id,
            job_id=name, status=status, command_redacted=command, expected=self._redact(request.expected),
            actual=reason, exit_code=exit_code, started_at=started, finished_at=utc_now(),
            environment=available, profile=self.profile,
            output_ref=self.snapshots.artifacts.put(content),
            output_total_bytes=total, output_truncated=total > self.profile.output_bytes,
            cleanup_confirmed=cleanup,
        )
