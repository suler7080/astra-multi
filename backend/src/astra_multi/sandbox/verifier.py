"""Executable Sandbox Constraint Verifier for Architecture Planning.

Enforces physical reality boundaries and technical constraints by generating
and executing simulation / static test scripts within an isolated subprocess sandbox.

If violations are detected:
- Test script exits with non-zero exit code (1) and emits detailed diagnostic failure logs.
- Verifier records a ToolCall with exit_code != 0.
- Verifier records Evidence with status = ValidationStatus.FAIL linked to the ToolCall.
- Verifier records a ValidationResult with status = ValidationStatus.FAIL.
- Verifier opens a BLOCKING Issue referencing the failed Evidence ID.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

from astra_multi.domain.models import (
    ID,
    ArtifactRef,
    Evidence,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    RequirementType,
    TaskSpec,
    TechStackTruthTable,
    ToolCall,
    ValidationResult,
    ValidationStatus,
    utc_now,
)
from astra_multi.domain.repositories import ArtifactStore
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.technical_grounding import (
    build_tech_stack_truth_table,
    extract_task_full_text,
    is_negated_or_prohibition,
)
from astra_multi.persistence.artifacts import FileArtifactStore

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SandboxVerificationOutcome:
    """Outcome of running the verification test script in the sandbox."""

    exit_code: int
    output_log: str
    violations: list[str]
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


class PlanSandboxVerifier:
    """Generates constraint verification test scripts, executes them in a sandbox, and records domain evidence."""

    def __init__(self, artifacts: ArtifactStore | None = None) -> None:
        if artifacts is None:
            temp_dir = Path(tempfile.gettempdir()) / "astra_artifacts"
            self.artifacts = FileArtifactStore(temp_dir)
        else:
            self.artifacts = artifacts

    def _extract_target_items(
        self,
        plan: PlanRevision | None,
        proposal: dict[str, Any] | Any = None,
    ) -> list[tuple[str, str]]:
        """Extracts candidate code snippets and deliverables with location metadata."""
        items: list[tuple[str, str]] = []

        if plan:
            for s in plan.steps:
                items.append((f"{s.id}:objective", s.objective or ""))
                items.append((f"{s.id}:validation", s.validation or ""))
                items.append((f"{s.id}:completion_criteria", s.completion_criteria or ""))
                for idx, d in enumerate(s.deliverables or []):
                    items.append((f"{s.id}:deliverable[{idx}]", str(d)))
                for idx, t in enumerate(s.targets or []):
                    items.append((f"{s.id}:target[{idx}]", str(t)))
                for rf in getattr(s, "requirement_fulfillments", []) or []:
                    rid = getattr(rf, "req_id", "") or rf.get("req_id", "")
                    cd = getattr(rf, "concrete_deliverable", "") or rf.get("concrete_deliverable", "")
                    sec = getattr(rf, "fulfilled_by_section", "") or rf.get("fulfilled_by_section", "")
                    vm = getattr(rf, "verification_method", "") or rf.get("verification_method", "")
                    items.append((f"{s.id}:fulfillment[{rid}]:section", sec))
                    items.append((f"{s.id}:fulfillment[{rid}]:deliverable", cd))
                    items.append((f"{s.id}:fulfillment[{rid}]:verification", vm))

            for da in getattr(plan, "design_artifacts", []) or []:
                items.append((f"{da.id}:{da.title}:content", da.content or ""))

            for d in getattr(plan, "decisions", []) or []:
                items.append((f"{d.id}:chosen", d.chosen or ""))
                items.append((f"{d.id}:rationale", d.rationale or ""))

        if proposal:
            if isinstance(proposal, dict):
                appr = proposal.get("approach", "")
                alts = proposal.get("alternatives", [])
                trades = proposal.get("tradeoffs", [])
            else:
                appr = getattr(proposal, "approach", "")
                alts = getattr(proposal, "alternatives", [])
                trades = getattr(proposal, "tradeoffs", [])

            if appr:
                items.append(("proposal:approach", str(appr)))
            for idx, a in enumerate(alts or []):
                items.append((f"proposal:alternative[{idx}]", str(a)))
            for idx, t in enumerate(trades or []):
                items.append((f"proposal:tradeoff[{idx}]", str(t)))

        return items

    def _build_active_rules(
        self,
        task: TaskSpec,
        truth_table: TechStackTruthTable | None = None,
    ) -> list[dict[str, Any]]:
        """Builds constraint rules that apply to the given task context."""
        if truth_table is None:
            truth_table = build_tech_stack_truth_table(task)

        active_tech_ids = {e.tech_id for e in truth_table.entries}
        rules: list[dict[str, Any]] = []

        # 1. file:// Protocol Grounding Rules
        if "TECH-FILE-PROTOCOL" in active_tech_ids:
            rules.extend([
                {
                    "rule_id": "TECH-FILE-001",
                    "name": "type=\"module\" forbidden under file:// protocol",
                    "regex": r'type\s*=\s*["\']module["\']',
                    "reason": "Browser blocks <script type=\"module\"> under file:// protocol due to CORS Origin: null",
                    "tech_id": "TECH-FILE-PROTOCOL",
                },
                {
                    "rule_id": "TECH-FILE-002",
                    "name": "ES Module import forbidden under file:// protocol",
                    "regex": r'\bimport\s+[\s\S]*?\bfrom\s+["\']|\bimport\s+["\']',
                    "reason": "ES Module import statement is blocked by browser under file:// protocol",
                    "tech_id": "TECH-FILE-PROTOCOL",
                },
                {
                    "rule_id": "TECH-FILE-003",
                    "name": "Local fetch for HTML/partials forbidden under file:// protocol",
                    "regex": r'fetch\s*\(\s*["\'](?:\./)?(?:header|footer|partials|\w+\.html)',
                    "reason": "Internal fetch() to local .html files is blocked by browser under file:// protocol",
                    "tech_id": "TECH-FILE-PROTOCOL",
                },
                {
                    "rule_id": "TECH-FILE-004",
                    "name": "ES Module phrasing in deliverable forbidden under file://",
                    "regex": r'\b(?:dùng|sử dụng|load|nhúng|import)\s+(?:es\s*module|module\s+es)\b',
                    "reason": "ES Module loading fails under direct file:// execution",
                    "tech_id": "TECH-FILE-PROTOCOL",
                },
            ])

        # 2. Real-time / Chat UX Rules
        if "TECH-REALTIME-CHAT" in active_tech_ids:
            rules.extend([
                {
                    "rule_id": "TECH-CHAT-001",
                    "name": "location.reload() forbidden on message send",
                    "regex": r'(?:window\.)?location\.reload\s*\(',
                    "reason": "Page reload after sending message causes UI flicker and destroys local state",
                    "tech_id": "TECH-REALTIME-CHAT",
                },
                {
                    "rule_id": "TECH-CHAT-002",
                    "name": "Page redirect forbidden on message send",
                    "regex": r'(?:window\.)?location\.href\s*=\s*|redirect\s+sau\s+(?:khi\s+gửi|mỗi)\s+tin\s+nhắn',
                    "reason": "Redirecting after message send destroys conversation view and user context",
                    "tech_id": "TECH-REALTIME-CHAT",
                },
            ])

        # 3. MockAPI Grounding Rules
        if "TECH-MOCKAPI" in active_tech_ids:
            rules.extend([
                {
                    "rule_id": "TECH-MOCKAPI-001",
                    "name": "Server-side JWT signature forbidden on MockAPI",
                    "regex": r'\bjwt\.sign\b|mockapi\s+sinh\s+jwt|sinh\s+jwt\s+từ\s+mockapi|server[- ]side\s+jwt',
                    "reason": "MockAPI.io is static JSON REST storage and cannot generate or sign JWTs on server",
                    "tech_id": "TECH-MOCKAPI",
                },
                {
                    "rule_id": "TECH-MOCKAPI-002",
                    "name": "Server-side bcrypt or token expiry check forbidden on MockAPI",
                    "regex": r'mockapi\s+(?:hash\s+mật\s+khẩu|bcrypt)|kiểm\s+tra\s+hết\s+hạn\s+token\s+ở\s+server\s+mockapi',
                    "reason": "MockAPI.io does not execute backend password hashing or token expiry validation",
                    "tech_id": "TECH-MOCKAPI",
                },
            ])

        # 4. No Framework / No Build Step Rules
        if "TECH-NO-BUILD" in active_tech_ids:
            rules.extend([
                {
                    "rule_id": "TECH-BUILD-001",
                    "name": "Build output directory forbidden when no build step specified",
                    "regex": r'(?:^|[\s/\\\'"])build/(?:[a-zA-Z0-9_\-\./]+)?|thư\s+mục\s+build|thu\s+muc\s+build',
                    "reason": "No bundler or build step is allowed; referencing 'build/' contradicts static constraint",
                    "tech_id": "TECH-NO-BUILD",
                },
                {
                    "rule_id": "TECH-BUILD-002",
                    "name": "Bundler build command forbidden",
                    "regex": r'\bnpm\s+run\s+build\b|\bvite\s+build\b|\bwebpack\s+build\b',
                    "reason": "Running build commands violates the constraint of zero build steps",
                    "tech_id": "TECH-NO-BUILD",
                },
            ])

        return rules

    def generate_verification_script(
        self,
        task: TaskSpec,
        plan: PlanRevision | None = None,
        proposal: dict[str, Any] | Any = None,
        truth_table: TechStackTruthTable | None = None,
    ) -> str:
        """Generates a standalone Python test script that checks plan snippets against active rules."""
        target_items = self._extract_target_items(plan, proposal)
        active_rules = self._build_active_rules(task, truth_table)

        items_json = json.dumps(target_items, ensure_ascii=False, indent=2)
        rules_json = json.dumps(active_rules, ensure_ascii=False, indent=2)

        script = f'''# -*- coding: utf-8 -*-
"""Autonomous Sandbox Test Script for Architecture Constraint Verification.
Generated by PlanSandboxVerifier.
"""

import json
import re
import sys

TARGET_ITEMS = {items_json}
RULES = {rules_json}

NEGATION_SIGNALS = [
    "không ", "khong ", "cấm ", "cam ", "tránh ", "tranh ",
    "do not ", "dont ", "don't ", "never ", "avoid ", "without ",
    "prohibit", "no ", "thay vì ", "thay vi ", "instead of ",
    "nghiêm cấm", "tuyệt đối không",
]

def is_negated(text: str, match_pos: int) -> bool:
    prefix = text[max(0, match_pos - 70):match_pos].lower()
    return any(sig in prefix for sig in NEGATION_SIGNALS)

def main():
    violations = []
    print("=" * 70)
    print("ASTRA MULTI-AGENT ARCHITECTURE CONSTRAINT SANDBOX VERIFIER")
    print(f"Testing {{len(TARGET_ITEMS)}} items against {{len(RULES)}} constraint rules...")
    print("=" * 70)

    for loc, text in TARGET_ITEMS:
        if not text or not isinstance(text, str):
            continue
        for rule in RULES:
            pattern = rule["regex"]
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    if is_negated(text, match.start()):
                        continue
                    violation_msg = (
                        f"[CONSTRAINT_VIOLATION] [{{rule['rule_id']}}] {{rule['name']}} in {{loc}}:\\n"
                        f"  Matched snippet: '{{match.group()}}'\\n"
                        f"  Physical constraint: {{rule['reason']}}"
                    )
                    violations.append(violation_msg)
                    print(violation_msg)
            except Exception as e:
                print(f"[ERROR] Failed checking rule {{rule['rule_id']}}: {{e}}", file=sys.stderr)

    print("-" * 70)
    if violations:
        print(f"FAILED: {{len(violations)}} constraint violation(s) detected in sandbox verification.", file=sys.stderr)
        sys.exit(1)
    else:
        print("PASSED: All deliverables and code snippets comply with physical technical constraints (0 violations).")
        sys.exit(0)

if __name__ == "__main__":
    main()
'''
        return script

    def execute_verification(
        self,
        run_id: str,
        script_content: str,
        timeout: float = 15.0,
        work_dir: Path | None = None,
    ) -> SandboxVerificationOutcome:
        """Executes the verification script in an isolated subprocess sandbox."""
        start_time = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="astra-sandbox-verify-") as temp_dir:
            target_dir = work_dir or Path(temp_dir)
            script_path = target_dir / "verify_constraints.py"
            script_path.write_text(script_content, encoding="utf-8")

            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"

            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                duration = time.monotonic() - start_time
                output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
                exit_code = proc.returncode
            except subprocess.TimeoutExpired as exc:
                duration = time.monotonic() - start_time
                out = exc.stdout or ""
                err = exc.stderr or ""
                output = f"TimeoutExpired: Sandbox verification exceeded {timeout}s limit.\n{out}\n{err}"
                exit_code = 124
            except Exception as exc:
                duration = time.monotonic() - start_time
                output = f"ExecutionError: Failed to run sandbox verification script: {exc}"
                exit_code = 1

        violations = [
            line.strip()
            for line in output.splitlines()
            if "[CONSTRAINT_VIOLATION]" in line
        ]

        return SandboxVerificationOutcome(
            exit_code=exit_code,
            output_log=output,
            violations=violations,
            duration_seconds=duration,
        )

    def record_verification_evidence(
        self,
        outcome: SandboxVerificationOutcome,
        run_id: str,
        snapshot_id: str | None,
        controller: WorkflowController,
        task: TaskSpec,
        plan: PlanRevision | None = None,
        script_content: str = "",
    ) -> tuple[ToolCall, Evidence, ValidationResult, list[Issue]]:
        # If passed, check if a pass has already been recorded for this plan revision
        base_rev = plan.revision if plan else 0
        pass_locator = f"sandbox://verification/plan-rev-{base_rev}"
        if outcome.passed:
            curr_state = controller.get_state()
            if any(e.locator == pass_locator for e in curr_state.evidence):
                return None, None, None, []

        # 1. Put raw execution output into artifact store
        raw_output_bytes = outcome.output_log.encode("utf-8")
        artifact_ref = self.artifacts.put(raw_output_bytes)

        call_id = f"CALL-SANDBOX-{uuid4().hex[:8]}"
        started = utc_now()
        finished = utc_now()

        # 2. Record ToolCall
        tool_call = ToolCall(
            id=call_id,
            run_id=run_id,
            request_hash=hashlib.sha256(script_content.encode("utf-8")).hexdigest(),
            arguments_redacted={
                "command": ["python", "verify_constraints.py"],
                "target": "plan_code_deliverables",
                "violations_count": len(outcome.violations),
            },
            environment="sandbox/subprocess-windows" if os.name == "nt" else "sandbox/subprocess-linux",
            snapshot_id=snapshot_id,
            exit_code=outcome.exit_code,
            output_artifact=artifact_ref,
            started_at=started,
            finished_at=finished,
        )
        controller.record_tool_call(tool_call)

        # 3. Record Evidence
        evid_id = f"EVID-{call_id}"
        locator = pass_locator if outcome.passed else f"sandbox://verification/{call_id}"
        evidence = Evidence(
            id=evid_id,
            run_id=run_id,
            source_type="tool",
            locator=locator,
            content_hash=artifact_ref.content_hash,
            captured_at=finished,
            snapshot_id=snapshot_id,
            tool_call_id=call_id,
            status=ValidationStatus.PASS if outcome.passed else ValidationStatus.FAIL,
            artifact=artifact_ref,
        )
        controller.record_evidence(evidence)

        # 4. Record ValidationResult
        valid_id = f"VALID-{call_id}"
        tech_req_ids = [r.id for r in task.requirements if r.req_type == RequirementType.TECH]
        if not tech_req_ids and task.requirements:
            tech_req_ids = [task.requirements[0].id]

        actual_summary = (
            outcome.output_log[:500]
            if not outcome.passed
            else "All technical constraints passed in sandbox execution (exit code 0)"
        )

        validation = ValidationResult(
            id=valid_id,
            run_id=run_id,
            status=ValidationStatus.PASS if outcome.passed else ValidationStatus.FAIL,
            expected="Plan code snippets and deliverables comply with physical technical constraints (exit code 0)",
            actual=actual_summary,
            exit_code=outcome.exit_code,
            tool_call_id=call_id,
            executed_at=finished,
            evidence_ids=[evid_id],
            requirement_ids=tech_req_ids,
        )
        controller.record_validation_result(validation)

        # 5. Open BLOCKING Issues if validation failed
        new_issues: list[Issue] = []
        base_rev = plan.revision if plan else 0

        if not outcome.passed:
            if outcome.violations:
                for idx, v in enumerate(outcome.violations):
                    raw_hash = hashlib.sha256(f"{run_id}:{call_id}:{idx}:{v}".encode("utf-8")).hexdigest()[:8]
                    iss_id = f"ISSUE-SANDBOX-{raw_hash}"
                    clean_v = v.replace("[CONSTRAINT_VIOLATION]", "").strip()
                    issue = Issue(
                        id=iss_id,
                        run_id=run_id,
                        severity=IssueSeverity.BLOCKING,
                        status=IssueStatus.OPEN,
                        based_on_revision=base_rev,
                        claim=f"Sandbox constraint verification failed: {clean_v[:200]}",
                        impact="Plan deliverables contain code patterns that fail technical constraint tests in the sandbox",
                        verification_request=f"Review sandbox execution log in evidence {evid_id}",
                        suggested_resolution="Remove forbidden patterns and adhere to physical environment constraints.",
                        requirement_ids=tech_req_ids,
                        evidence_ids=[evid_id],
                    )
                    try:
                        controller.record_issue(issue)
                        new_issues.append(issue)
                    except Exception as exc:
                        logger.warning("Could not record sandbox issue %s: %s", iss_id, exc)
            else:
                iss_id = f"ISSUE-SANDBOX-{uuid4().hex[:8]}"
                issue = Issue(
                    id=iss_id,
                    run_id=run_id,
                    severity=IssueSeverity.BLOCKING,
                    status=IssueStatus.OPEN,
                    based_on_revision=base_rev,
                    claim=f"Sandbox verification script exited with error (code {outcome.exit_code})",
                    impact="Executable verification failed in sandbox",
                    verification_request=f"Review sandbox execution log in evidence {evid_id}",
                    suggested_resolution="Fix constraint verification failure in plan",
                    requirement_ids=tech_req_ids,
                    evidence_ids=[evid_id],
                )
                try:
                    controller.record_issue(issue)
                    new_issues.append(issue)
                except Exception as exc:
                    logger.warning("Could not record sandbox issue %s: %s", iss_id, exc)

        return tool_call, evidence, validation, new_issues

    def verify(
        self,
        task: TaskSpec,
        plan: PlanRevision | None,
        proposal: dict[str, Any] | Any = None,
        truth_table: TechStackTruthTable | None = None,
        controller: WorkflowController | None = None,
        snapshot_id: str | None = None,
    ) -> tuple[SandboxVerificationOutcome, ToolCall | None, Evidence | None, ValidationResult | None, list[Issue]]:
        """End-to-end verification pipeline: generate -> execute -> record."""
        active_rules = self._build_active_rules(task, truth_table)
        if not active_rules:
            outcome = SandboxVerificationOutcome(
                exit_code=0,
                output_log="No active technical constraints applicable to task.",
                violations=[],
                duration_seconds=0.0,
            )
            return outcome, None, None, None, []

        script = self.generate_verification_script(task, plan, proposal, truth_table)
        run_id = controller.get_state().run.id if controller else "run-standalone"
        outcome = self.execute_verification(run_id, script)

        if controller is not None:
            curr_state = controller.get_state()
            tc, evid, val, issues = self.record_verification_evidence(
                outcome=outcome,
                run_id=curr_state.run.id,
                snapshot_id=snapshot_id or curr_state.run.snapshot_id,
                controller=controller,
                task=task,
                plan=plan,
                script_content=script,
            )
            return outcome, tc, evid, val, issues

        return outcome, None, None, None, []
