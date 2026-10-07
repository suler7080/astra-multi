from __future__ import annotations

from datetime import datetime

from pydantic import JsonValue

from .commands import (
    AddRecord,
    AnswerQuestion,
    ChangeIssue,
    CommitPlan,
    Mutation,
    ReviseTask,
    TransitionRun,
)
from .models import (
    TERMINAL,
    BudgetReservation,
    Claim,
    Decision,
    Evidence,
    Issue,
    IssueHistory,
    IssueSeverity,
    IssueStatus,
    ModelCall,
    Proposal,
    Question,
    RequirementChange,
    RunPhase,
    RunState,
    RunStatus,
    ToolCall,
    ValidationResult,
)


class DomainError(ValueError):
    pass


class RevisionConflict(DomainError):
    pass


class InvalidState(DomainError):
    pass


class LeaseLost(DomainError):
    pass


class OperationConflict(DomainError):
    pass


PHASE_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.INTAKE: frozenset({RunPhase.SNAPSHOT, RunPhase.INDEPENDENT_ANALYSIS}),
    RunPhase.SNAPSHOT: frozenset({RunPhase.INVESTIGATE}),
    RunPhase.INVESTIGATE: frozenset({RunPhase.INDEPENDENT_ANALYSIS}),
    RunPhase.INDEPENDENT_ANALYSIS: frozenset({RunPhase.PROPOSE}),
    RunPhase.PROPOSE: frozenset({RunPhase.REVIEW}),
    RunPhase.REVIEW: frozenset({RunPhase.VERIFY, RunPhase.REVISE}),
    RunPhase.VERIFY: frozenset({RunPhase.REVISE}),
    RunPhase.REVISE: frozenset({RunPhase.QUALITY_GATE}),
    RunPhase.QUALITY_GATE: frozenset({RunPhase.REVIEW, RunPhase.EXPORT, RunPhase.PROPOSE}),
    RunPhase.EXPORT: frozenset(),
}

ISSUE_TRANSITIONS: dict[IssueStatus, frozenset[IssueStatus]] = {
    IssueStatus.OPEN: frozenset(
        {IssueStatus.INVESTIGATING, IssueStatus.REJECTED, IssueStatus.DUPLICATE}
    ),
    IssueStatus.INVESTIGATING: frozenset(
        {IssueStatus.PROPOSED_RESOLUTION, IssueStatus.REJECTED, IssueStatus.DUPLICATE}
    ),
    IssueStatus.PROPOSED_RESOLUTION: frozenset(
        {IssueStatus.INVESTIGATING, IssueStatus.RESOLVED, IssueStatus.REJECTED}
    ),
    IssueStatus.RESOLVED: frozenset(),
    IssueStatus.REJECTED: frozenset(),
    IssueStatus.DUPLICATE: frozenset(),
}


def change_issue(state: RunState, command: ChangeIssue, now: datetime) -> Issue:
    issue = next((item for item in state.issues if item.id == command.issue_id), None)
    if issue is None or command.status not in ISSUE_TRANSITIONS[issue.status]:
        raise InvalidState("invalid issue transition")
    resolution = command.resolution
    closed = command.status in {IssueStatus.RESOLVED, IssueStatus.REJECTED}
    if closed and resolution is None:
        raise InvalidState("closing requires a resolution")
    if command.status == IssueStatus.PROPOSED_RESOLUTION and resolution is None:
        raise InvalidState("proposed resolution requires a resolution")
    if closed and issue.severity == IssueSeverity.BLOCKING:
        assert resolution is not None
        change = resolution.requirement_change
        if change:
            if (
                change.task_revision != state.task.revision
                or change not in state.task_changes
            ):
                raise InvalidState(
                    "requirement change must reference a committed task revision"
                )
            current = {r.id: (r.text, r.acceptance) for r in state.task.requirements}
            previous = {
                r.id: (r.text, r.acceptance) for r in state.tasks[-2].requirements
            }
            if not issue.requirement_ids or not any(
                current.get(key) != previous.get(key) for key in issue.requirement_ids
            ):
                raise InvalidState("referenced requirements have not changed")
        elif not (
            state.plan
            and resolution.reviewed_revision == state.plan.revision
            and resolution.reviewed_revision > issue.based_on_revision
            and state.plan.requirements_revision == state.task.revision
            and issue.id in state.plan.issues_addressed
            and resolution.reviewer
            and resolution.reviewer != command.actor
            and resolution.review_result == "PASS"
            and resolution.review_note
        ):
            raise InvalidState(
                "blocking issue requires independent review on the new current plan"
            )
    if command.status == IssueStatus.DUPLICATE:
        target = next(
            (item for item in state.issues if item.id == command.duplicate_of), None
        )
        if (
            target is None
            or target.id == issue.id
            or target.status == IssueStatus.DUPLICATE
        ):
            raise InvalidState(
                "duplicate must link directly to another canonical issue"
            )
        if (
            issue.severity == IssueSeverity.BLOCKING
            and target.severity != IssueSeverity.BLOCKING
        ):
            raise InvalidState("blocking duplicate must retain a blocking target")
    elif command.duplicate_of is not None:
        raise InvalidState("duplicate link only allowed for duplicate status")
    history = IssueHistory(
        status=command.status,
        actor=command.actor,
        timestamp=now,
        reason=command.reason,
        resolution=resolution,
        duplicate_of=command.duplicate_of,
    )
    return Issue.model_validate(
        {
            **issue.model_dump(),
            "status": command.status,
            "resolution": resolution,
            "duplicate_of": command.duplicate_of,
            "history": [*issue.history, history],
        }
    )


def apply_mutation(
    state: RunState, command: Mutation, now: datetime
) -> tuple[RunState, dict[str, JsonValue]]:
    if command.expected_revision != state.run.revision:
        raise RevisionConflict(
            f"expected {command.expected_revision}, current {state.run.revision}"
        )
    if state.run.status in TERMINAL:
        raise InvalidState("terminal runs are immutable; create a new run")
    updated = state.model_copy(deep=True)
    result: dict[str, JsonValue] = {}
    if isinstance(command, CommitPlan):
        current = state.plan.revision if state.plan else 0
        if (
            command.plan.based_on_revision != current
            or command.plan.requirements_revision != state.task.revision
        ):
            raise RevisionConflict("plan or requirements base revision is stale")
        updated.plans.append(command.plan)
        result = {"plan_id": command.plan.id, "plan_revision": command.plan.revision}
    elif isinstance(command, AddRecord):
        record = command.record
        if isinstance(record, Issue):
            if (
                record.status != IssueStatus.OPEN
                or record.history
                or record.resolution
                or record.duplicate_of
            ):
                raise InvalidState("issues enter as open; use lifecycle commands")
            if record.based_on_revision != (state.plan.revision if state.plan else 0):
                raise RevisionConflict("issue base revision is stale")
            record = Issue.model_validate(
                {
                    **record.model_dump(),
                    "history": [
                        IssueHistory(
                            status=IssueStatus.OPEN,
                            actor=command.actor,
                            timestamp=now,
                            reason="Issue opened",
                        )
                    ],
                }
            )
            updated.issues.append(record)
        elif isinstance(record, Claim):
            updated.claims.append(record)
        elif isinstance(record, Evidence):
            updated.evidence.append(record)
        elif isinstance(record, Proposal):
            if record.base_revision != (state.plan.revision if state.plan else 0):
                raise RevisionConflict("proposal base revision is stale")
            updated.proposals.append(record)
        elif isinstance(record, Decision):
            updated.decisions.append(record)
        elif isinstance(record, ToolCall):
            updated.tool_calls.append(record)
        elif isinstance(record, ModelCall):
            updated.model_calls.append(record)
        elif isinstance(record, Question):
            if record.answer is not None:
                raise InvalidState("questions enter unanswered")
            updated.questions.append(record)
        elif isinstance(record, ValidationResult):
            updated.validations.append(record)
        elif isinstance(record, BudgetReservation):
            updated.reservations.append(record)
        result = {"record_id": record.id}
    elif isinstance(command, ChangeIssue):
        issue = change_issue(state, command, now)
        updated = updated.model_copy(
            update={
                "issues": [
                    issue if item.id == issue.id else item for item in updated.issues
                ]
            }
        )
        result = {"issue_id": issue.id, "status": issue.status.value}
    elif isinstance(command, AnswerQuestion):
        question = next(
            (q for q in state.questions if q.id == command.question_id), None
        )
        if (
            question is None
            or question.answer is not None
            or state.run.status != RunStatus.WAITING_FOR_INPUT
        ):
            raise InvalidState(
                "answer requires an unanswered question on a waiting run"
            )
        answer = Question.model_validate(
            {
                **question.model_dump(),
                "answer": command.answer,
                "answered_by": command.actor,
                "answered_at": now,
            }
        )
        updated = updated.model_copy(
            update={
                "questions": [
                    answer if q.id == answer.id else q for q in updated.questions
                ]
            }
        )
        result = {"question_id": question.id}
    elif isinstance(command, ReviseTask):
        if (
            command.task.id != state.task.id
            or command.task.revision != state.task.revision + 1
        ):
            raise RevisionConflict("task must retain identity and increment revision")
        updated.tasks.append(command.task)
        updated.task_changes.append(
            RequirementChange(
                task_revision=command.task.revision,
                actor=command.actor,
                reason=command.reason,
            )
        )
        updated = updated.model_copy(
            update={
                "run": updated.run.model_copy(
                    update={"task_revision": command.task.revision}
                )
            }
        )
        result = {"task_revision": command.task.revision, "reason": command.reason}
    elif isinstance(command, TransitionRun):
        if command.status == RunStatus.FINAL and command.actor not in ("P4-quality-service", "quality-service"):
            raise InvalidState("FINAL is reserved for the P4 quality service")
        if command.status in TERMINAL:
            if not command.reason or command.phase != state.run.phase:
                raise InvalidState(
                    "terminal transition retains phase and requires a reason"
                )
        elif command.status == RunStatus.WAITING_FOR_INPUT:
            if (
                state.run.status != RunStatus.RUNNING
                or command.phase != state.run.phase
                or not any(q.answer is None for q in state.questions)
            ):
                raise InvalidState(
                    "waiting requires a pending question and retains phase"
                )
        elif state.run.status == RunStatus.WAITING_FOR_INPUT:
            if command.phase != state.run.phase or any(
                q.blocking and q.answer is None for q in state.questions
            ):
                raise InvalidState("resume retains phase and requires blocking answers")
        elif command.phase not in PHASE_TRANSITIONS[state.run.phase]:
            raise InvalidState("invalid phase transition")
        updated = updated.model_copy(
            update={
                "run": updated.run.model_copy(
                    update={
                        "phase": command.phase,
                        "status": command.status,
                        "stop_reason": command.reason,
                    }
                )
            }
        )
        result = {"phase": command.phase.value, "status": command.status.value}
    updated = updated.model_copy(
        update={
            "run": updated.run.model_copy(
                update={"revision": state.run.revision + 1, "updated_at": now}
            )
        }
    )
    return RunState.model_validate(updated.model_dump()), result
