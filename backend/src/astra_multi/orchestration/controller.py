"""Deterministic controller for orchestrating domain state mutations.

P3.3 Controller and State Transitions:
- Exclusively commits domain changes via P1 domain commands (CommitPlan, AddRecord, ChangeIssue, TransitionRun).
- Applies fenced leases and checks expected revision.
- Records model calls, claims, and decisions.
"""

from __future__ import annotations

import hashlib
import threading

from astra_multi.domain.commands import (
    AddRecord,
    AnswerQuestion,
    CommitPlan,
    ReviseTask,
    TransitionRun,
)
from astra_multi.domain.models import (
    Decision,
    Issue,
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
        cmd = AddRecord(
            expected_revision=state.run.revision,
            node="review",
            logical_operation_id=f"issue-{issue.id}",
            actor=self.actor,
            record=issue,
        )
        self.repository.commit(self.lease.run_id, cmd, self.lease)
        return self.get_state()

    def commit_plan_revision(self, plan: PlanRevision) -> RunState:
        state = self.get_state()
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
            input_hash = hashlib.sha256(input_data.encode("utf-8")).hexdigest()
            call = ModelCall(
                id=call_id,
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
                logical_operation_id=f"model-call-{call_id}",
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
