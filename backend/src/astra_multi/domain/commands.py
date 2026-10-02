from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .models import (
    ID,
    BudgetReservation,
    Claim,
    Contract,
    Decision,
    Evidence,
    Issue,
    IssueResolution,
    IssueStatus,
    ModelCall,
    PlanRevision,
    Proposal,
    Question,
    RunPhase,
    RunStatus,
    TaskSpec,
    Text,
    ToolCall,
    ValidationResult,
)


class Command(Contract):
    expected_revision: Annotated[int, Field(ge=1, strict=True)]
    node: ID
    logical_operation_id: ID
    actor: Text


class CommitPlan(Command):
    kind: Literal["commit_plan"] = "commit_plan"
    plan: PlanRevision


Record = (
    Claim
    | Evidence
    | Proposal
    | Issue
    | Decision
    | ToolCall
    | ModelCall
    | Question
    | ValidationResult
    | BudgetReservation
)


class AddRecord(Command):
    kind: Literal["add_record"] = "add_record"
    record: Record


class TransitionRun(Command):
    kind: Literal["transition_run"] = "transition_run"
    phase: RunPhase
    status: RunStatus
    reason: Text | None = None


class ChangeIssue(Command):
    kind: Literal["change_issue"] = "change_issue"
    issue_id: ID
    status: IssueStatus
    reason: Text
    resolution: IssueResolution | None = None
    duplicate_of: ID | None = None


class AnswerQuestion(Command):
    kind: Literal["answer_question"] = "answer_question"
    question_id: ID
    answer: Text


class ReviseTask(Command):
    kind: Literal["revise_task"] = "revise_task"
    task: TaskSpec
    reason: Text


Mutation = Annotated[
    CommitPlan | AddRecord | TransitionRun | ChangeIssue | AnswerQuestion | ReviseTask,
    Field(discriminator="kind"),
]
