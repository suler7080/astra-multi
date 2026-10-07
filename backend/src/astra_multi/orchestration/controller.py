"""Deterministic controller for orchestrating domain state mutations.

P3.3 Controller and State Transitions:
- Exclusively commits domain changes via P1 domain commands (CommitPlan, AddRecord, ChangeIssue, TransitionRun).
- Applies fenced leases and checks expected revision.
- Records model calls, claims, and decisions.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Literal
import uuid

from astra_multi.domain.commands import (
    AddRecord,
    AnswerQuestion,
    ChangeIssue,
    CommitPlan,
    ReviseTask,
    TransitionRun,
)
from astra_multi.domain.models import (
    Decision,
    Issue,
    IssueResolution,
    IssueSeverity,
    IssueStatus,
    Lease,
    ModelCall,
    PlanRevision,
    Proposal,
    Question,
    RunPhase,
    RunState,
    RunStatus,
    TaskSpec,
)
from astra_multi.domain.repositories import RunRepository


class WorkflowController:
    """Coordinates domain persistence and state transitions for a run under lease."""

    def __init__(
        self,
        repository: RunRepository,
        lease: Lease,
        actor: str = "orchestration-controller",
    ) -> None:
        self.repository = repository
        self.lease = lease
        self.actor = actor
        self._lock = threading.Lock()

    def get_state(self) -> RunState:
        return self.repository.load(self.lease.run_id)

    def transition_phase(self, new_phase: RunPhase, new_status: RunStatus = RunStatus.RUNNING, reason: str | None = None) -> RunState:
        state = self.get_state()
        if state.run.phase == new_phase and state.run.status == new_status:
            return state
        cmd = TransitionRun(
            expected_revision=state.run.revision,
            node=f"transition-{new_phase.value.lower()}",
            logical_operation_id=f"phase-{new_phase.value}-{state.run.revision}",
            actor=self.actor,
            phase=new_phase,
            status=new_status,
            reason=reason,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def record_proposal(self, proposal: Proposal) -> RunState:
        state = self.get_state()
        if any(p.id == proposal.id for p in state.proposals):
            return state
        cmd = AddRecord(
            expected_revision=state.run.revision,
            node="propose",
            logical_operation_id=f"proposal-{proposal.id}",
            actor=self.actor,
            record=proposal,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def record_issue(self, issue: Issue) -> RunState:
        state = self.get_state()
        if any(i.id == issue.id for i in state.issues):
            return state
        cmd = AddRecord(
            expected_revision=state.run.revision,
            node="review",
            logical_operation_id=f"issue-{issue.id}",
            actor=self.actor,
            record=issue,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def resolve_issue(
        self,
        issue_id: str,
        reviewer: str,
        review_result: Literal["PASS", "FAIL"],
        review_note: str,
        resolution_text: str = "Resolved based on plan revision",
        evidence_ids: list[str] | None = None,
        node: str = "review",
    ) -> RunState:
        state = self.get_state()
        issue = next((i for i in state.issues if i.id == issue_id), None)
        if not issue:
            return state
        if issue.status == IssueStatus.RESOLVED:
            return state

        # Step 1: OPEN -> INVESTIGATING
        if issue.status == IssueStatus.OPEN:
            cmd = ChangeIssue(
                expected_revision=state.run.revision,
                node=node,
                logical_operation_id=f"issue-{issue_id}-investigating",
                actor=self.actor,
                issue_id=issue_id,
                status=IssueStatus.INVESTIGATING,
                reason="Investigating issue during review",
            )
            self.repository.commit(self.lease.run_id, cmd, self.lease)
            state = self.get_state()
            issue = next((i for i in state.issues if i.id == issue_id), None)
            if not issue:
                return state

        # Step 2: INVESTIGATING -> PROPOSED_RESOLUTION
        if issue.status == IssueStatus.INVESTIGATING:
            cmd = ChangeIssue(
                expected_revision=state.run.revision,
                node=node,
                logical_operation_id=f"issue-{issue_id}-proposed",
                actor=self.actor,
                issue_id=issue_id,
                status=IssueStatus.PROPOSED_RESOLUTION,
                reason="Proposed resolution",
                resolution=IssueResolution(text=resolution_text),
            )
            self.repository.commit(self.lease.run_id, cmd, self.lease)
            state = self.get_state()
            issue = next((i for i in state.issues if i.id == issue_id), None)
            if not issue:
                return state

        # Step 3: PROPOSED_RESOLUTION -> RESOLVED (only if review_result == PASS)
        if issue.status == IssueStatus.PROPOSED_RESOLUTION and review_result == "PASS":
            resolution = IssueResolution(
                text=resolution_text,
                evidence_ids=evidence_ids or [],
                reviewed_revision=state.plan.revision if state.plan else None,
                reviewer=reviewer,
                review_result=review_result,
                review_note=review_note,
            )
            cmd = ChangeIssue(
                expected_revision=state.run.revision,
                node=node,
                logical_operation_id=f"issue-{issue_id}-resolved",
                actor=self.actor,
                issue_id=issue_id,
                status=IssueStatus.RESOLVED,
                reason=review_note,
                resolution=resolution,
            )
            self.repository.commit(self.lease.run_id, cmd, self.lease)
            return self.get_state()

        return state

    def commit_plan_revision(self, plan: PlanRevision) -> RunState:
        state = self.get_state()
        if any(p.revision == plan.revision for p in state.plans):
            return state
        cmd = CommitPlan(
            expected_revision=state.run.revision,
            node="revise",
            logical_operation_id=f"plan-rev-{plan.revision}",
            actor=self.actor,
            plan=plan,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def record_decision(self, decision: Decision) -> RunState:
        state = self.get_state()
        if any(d.id == decision.id for d in state.decisions):
            return state
        cmd = AddRecord(
            expected_revision=state.run.revision,
            node="revise",
            logical_operation_id=f"decision-{decision.id}",
            actor=self.actor,
            record=decision,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def record_model_call(
        self,
        call_id: str,
        role: str,
        provider: str,
        model_id: str,
        prompt_version: str,
        input_data: str,
        usage: dict[str, int] | None = None,
        estimated_cost: float = 0.0,
        attempts: int = 1,
    ) -> RunState:
        with self._lock:
            state = self.get_state()
            existing_call_ids = {m.id for m in state.model_calls}
            final_call_id = call_id
            if final_call_id in existing_call_ids:
                final_call_id = f"{call_id}-{uuid.uuid4().hex[:4]}"
            input_hash = hashlib.sha256(input_data.encode("utf-8")).hexdigest()
            call = ModelCall(
                id=final_call_id,
                run_id=state.run.id,
                role=role,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_hash=input_hash,
                usage=usage or {},
                estimated_cost=estimated_cost,
                attempts=attempts,
            )
            cmd = AddRecord(
                expected_revision=state.run.revision,
                node="model-gateway",
                logical_operation_id=f"model-call-{final_call_id}",
                actor=self.actor,
                record=call,
            )
            self.repository.commit(self.lease.run_id, cmd, self.lease)
            return self.get_state()

    def ask_question(self, question: Question) -> RunState:
        state = self.get_state()
        cmd = AddRecord(
            expected_revision=state.run.revision,
            node="question-node",
            logical_operation_id=f"question-{question.id}",
            actor=self.actor,
            record=question,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def answer_question(self, question_id: str, answer_text: str) -> RunState:
        state = self.get_state()
        cmd = AnswerQuestion(
            expected_revision=state.run.revision,
            node="input-handler",
            logical_operation_id=f"answer-{question_id}",
            actor=self.actor,
            question_id=question_id,
            answer=answer_text,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def revise_task(self, new_task: TaskSpec, reason: str) -> RunState:
        state = self.get_state()
        cmd = ReviseTask(
            expected_revision=state.run.revision,
            node="task-updater",
            logical_operation_id=f"task-rev-{new_task.revision}",
            actor=self.actor,
            task=new_task,
            reason=reason,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()
