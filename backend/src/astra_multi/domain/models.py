"""Versioned contracts independent of orchestration and provider SDKs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

ID = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Text = Annotated[
    str, Field(min_length=1), AfterValidator(lambda s: s if s.strip() else _empty())
]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(ge=1, strict=True)]


def _empty() -> str:
    raise ValueError("text must not be blank")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


UTC = Annotated[datetime, AfterValidator(_utc)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    schema_version: Literal[1] = 1


class Entity(Contract):
    id: ID
    created_at: UTC = Field(default_factory=utc_now)


class ValidationStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"


class RunPhase(str, Enum):
    INTAKE = "INTAKE"
    SNAPSHOT = "SNAPSHOT"
    INVESTIGATE = "INVESTIGATE"
    INDEPENDENT_ANALYSIS = "INDEPENDENT_ANALYSIS"
    PROPOSE = "PROPOSE"
    REVIEW = "REVIEW"
    VERIFY = "VERIFY"
    REVISE = "REVISE"
    QUALITY_GATE = "QUALITY_GATE"
    EXPORT = "EXPORT"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    FINAL = "FINAL"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset(
    {RunStatus.FINAL, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED}
)


class IssueSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class IssueStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PROPOSED_RESOLUTION = "proposed_resolution"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class Requirement(Entity):
    text: Text
    acceptance: Text


class TaskSpec(Entity):
    revision: Revision = 1
    goal: Text
    requirements: list[Requirement] = Field(min_length=1)
    constraints: list[Text] = Field(default_factory=list)
    non_goals: list[Text] = Field(default_factory=list)
    acceptance_criteria: list[Text] = Field(default_factory=list)
    unknowns: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_requirements(self) -> Self:
        unique(self.requirements)
        return self


class ArtifactRef(Contract):
    content_hash: Hash
    size: Annotated[int, Field(ge=0, strict=True)]


class Snapshot(Entity):
    source_path: Text
    commit_if_any: str | None = None
    dirty: bool = False
    manifest_hash: Hash
    file_hashes: dict[str, Hash]
    excluded_patterns: list[str] = Field(default_factory=list)


class Budget(Contract):
    token_limit: Annotated[int, Field(ge=0)] = 0
    cost_limit: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0


class Run(Entity):
    task_id: ID
    task_revision: Revision
    snapshot_id: ID | None
    mode: Literal["repo", "greenfield"]
    revision: Revision = 1
    phase: RunPhase = RunPhase.INTAKE
    status: RunStatus = RunStatus.RUNNING
    stop_reason: Text | None = None
    config_hash: Hash
    budget: Budget = Field(default_factory=Budget)
    updated_at: UTC = Field(default_factory=utc_now)
    parent_run_id: ID | None = None

    @model_validator(mode="after")
    def snapshot_contract(self) -> Self:
        if (self.mode == "repo") != (self.snapshot_id is not None):
            raise ValueError(
                "repo requires snapshot_id; greenfield requires explicit null"
            )
        if (
            self.status in TERMINAL
            and self.status != RunStatus.FINAL
            and not self.stop_reason
        ):
            raise ValueError("terminal runs need a stop_reason")
        return self


class RunEntity(Entity):
    run_id: ID


class Claim(RunEntity):
    text: Text
    kind: Literal["fact", "assumption", "proposal", "unknown"]
    evidence_ids: list[ID] = Field(default_factory=list)
    snapshot_id: ID | None


class ValidationResult(RunEntity):
    status: ValidationStatus = ValidationStatus.NOT_RUN
    expected: Text
    actual: Text | None = None
    exit_code: int | None = None
    tool_call_id: ID | None = None
    executed_at: UTC | None = None
    requirement_ids: list[ID] = Field(default_factory=list)
    step_ids: list[ID] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)

    @model_validator(mode="after")
    def execution_contract(self) -> Self:
        executed = (self.actual, self.exit_code, self.tool_call_id, self.executed_at)
        if self.status == ValidationStatus.NOT_RUN:
            if any(value is not None for value in executed):
                raise ValueError("NOT_RUN cannot contain execution results")
        elif any(value is None for value in executed):
            raise ValueError(
                "PASS/FAIL require actual, exit_code, tool_call_id and executed_at"
            )
        if self.status == ValidationStatus.PASS and self.exit_code != 0:
            raise ValueError("PASS requires exit_code=0")
        return self


class Evidence(RunEntity):
    source_type: Literal["repo", "tool", "document", "user"]
    locator: Text
    content_hash: Hash
    captured_at: UTC
    snapshot_id: ID | None
    tool_call_id: ID | None = None
    status: ValidationStatus = ValidationStatus.NOT_RUN
    artifact: ArtifactRef | None = None

    @model_validator(mode="after")
    def evidence_contract(self) -> Self:
        if self.source_type == "repo" and self.snapshot_id is None:
            raise ValueError("repo evidence needs snapshot_id")
        if self.source_type == "tool" and self.tool_call_id is None:
            raise ValueError("tool evidence needs tool_call_id")
        if self.status != ValidationStatus.NOT_RUN and self.tool_call_id is None:
            raise ValueError("executed evidence needs tool_call_id")
        if self.artifact and self.artifact.content_hash != self.content_hash:
            raise ValueError("artifact hash must match evidence hash")
        return self


class Proposal(RunEntity):
    author_role: Text
    base_revision: Annotated[int, Field(ge=0, strict=True)]
    approach: Text
    alternatives: list[Text] = Field(default_factory=list)
    tradeoffs: list[Text] = Field(default_factory=list)
    claim_ids: list[ID] = Field(default_factory=list)
    requirement_coverage: dict[ID, Text] = Field(default_factory=dict)


class RequirementChange(Contract):
    task_revision: Revision
    actor: Text
    reason: Text


class IssueResolution(Contract):
    text: Text
    evidence_ids: list[ID] = Field(default_factory=list)
    reviewed_revision: Revision | None = None
    reviewer: Text | None = None
    review_result: Literal["PASS", "FAIL"] | None = None
    review_note: Text | None = None
    requirement_change: RequirementChange | None = None


class IssueHistory(Contract):
    status: IssueStatus
    actor: Text
    timestamp: UTC
    reason: Text
    resolution: IssueResolution | None = None
    duplicate_of: ID | None = None


class Issue(RunEntity):
    severity: IssueSeverity
    status: IssueStatus = IssueStatus.OPEN
    based_on_revision: Annotated[int, Field(ge=0, strict=True)]
    claim: Text
    impact: Text
    verification_request: Text | None = None
    suggested_resolution: Text
    requirement_ids: list[ID] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    resolution: IssueResolution | None = None
    duplicate_of: ID | None = None
    history: list[IssueHistory] = Field(default_factory=list)

    @model_validator(mode="after")
    def basis(self) -> Self:
        if not self.evidence_ids and not self.verification_request:
            raise ValueError("issue needs evidence or a verification request")
        if (
            self.status in {IssueStatus.RESOLVED, IssueStatus.REJECTED}
            and self.resolution is None
        ):
            raise ValueError("closed issue needs resolution")
        if self.status == IssueStatus.DUPLICATE and not self.duplicate_of:
            raise ValueError("duplicate needs a target")
        return self


class Decision(RunEntity):
    question: Text
    chosen: Text
    rationale: Text
    alternatives: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    related_issues: list[ID] = Field(default_factory=list)


class PlanStep(Entity):
    objective: Text
    requirement_ids: list[ID] = Field(min_length=1)
    dependencies: list[ID] = Field(default_factory=list)
    targets: list[Text] = Field(default_factory=list)
    validation: Text
    deliverables: list[Text] = Field(min_length=1)
    completion_criteria: list[Text] = Field(min_length=1)
    evidence_ids: list[ID] = Field(default_factory=list)


class PlanRevision(RunEntity):
    revision: Revision
    based_on_revision: Annotated[int, Field(ge=0, strict=True)]
    requirements_revision: Revision
    snapshot_id: ID | None
    steps: list[PlanStep] = Field(min_length=1)
    decisions: list[Decision] = Field(default_factory=list)
    risks: list[Text] = Field(default_factory=list)
    issues_addressed: list[ID] = Field(default_factory=list)

    @model_validator(mode="after")
    def step_graph(self) -> Self:
        unique(self.steps)
        unique(self.decisions)
        if self.revision != self.based_on_revision + 1:
            raise ValueError("plan revisions must be consecutive")
        remaining = {step.id: set(step.dependencies) for step in self.steps}
        if any(not deps <= remaining.keys() for deps in remaining.values()):
            raise ValueError("unknown step dependency")
        while remaining:
            ready = {key for key, deps in remaining.items() if not deps}
            if not ready:
                raise ValueError("step dependency cycle")
            remaining = {
                key: deps - ready for key, deps in remaining.items() if key not in ready
            }
        return self


class ToolCall(RunEntity):
    request_hash: Hash
    arguments_redacted: dict[str, JsonValue]
    environment: Text
    snapshot_id: ID | None
    exit_code: int | None
    output_artifact: ArtifactRef | None
    started_at: UTC
    finished_at: UTC | None

    @model_validator(mode="after")
    def execution_contract(self) -> Self:
        if (self.exit_code is None) != (self.finished_at is None):
            raise ValueError("tool completion needs exit code and finished_at")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("tool cannot finish before it starts")
        return self


class ModelCall(RunEntity):
    role: Text
    provider: Text
    model_id: Text
    prompt_version: Text
    input_hash: Hash
    usage: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    estimated_cost: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    attempts: Annotated[int, Field(ge=1)] = 1
    output_artifact: ArtifactRef | None = None


class Question(RunEntity):
    text: Text
    blocking: bool = True
    requirement_ids: list[ID] = Field(default_factory=list)
    answer: Text | None = None
    answered_by: Text | None = None
    answered_at: UTC | None = None

    @model_validator(mode="after")
    def answer_contract(self) -> Self:
        fields = (self.answer, self.answered_by, self.answered_at)
        if any(value is not None for value in fields) and any(
            value is None for value in fields
        ):
            raise ValueError("answer requires actor and timestamp")
        return self


class BudgetReservation(RunEntity):
    operation_id: ID
    tokens: Annotated[int, Field(ge=0)]
    cost: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    status: Literal["reserved", "settled", "released"] = "reserved"


class Event(Entity):
    run_id: ID
    sequence: Revision
    type: Text
    actor: Text
    revision: Revision
    payload: dict[str, JsonValue]
    payload_ref: ArtifactRef | None = None
    timestamp: UTC


class OperationRecord(Entity):
    run_id: ID
    node: ID
    logical_operation_id: ID
    request_hash: Hash
    revision: Revision
    event_sequence: Revision
    result: dict[str, JsonValue]


class Lease(Contract):
    run_id: ID
    owner: ID
    token: ID
    epoch: Revision
    expires_at: UTC


class CheckpointRef(Contract):
    run_id: ID
    revision: Revision
    task_id: ID
    task_revision: Revision
    plan_id: ID | None


def unique(entities: Sequence[Entity]) -> None:
    if len({entity.id for entity in entities}) != len(entities):
        raise ValueError("duplicate IDs")


class RunState(Contract):
    run: Run
    tasks: list[TaskSpec] = Field(min_length=1)
    snapshot: Snapshot | None
    task_changes: list[RequirementChange] = Field(default_factory=list)
    plans: list[PlanRevision] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model_calls: list[ModelCall] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    reservations: list[BudgetReservation] = Field(default_factory=list)

    @property
    def task(self) -> TaskSpec:
        return self.tasks[-1]

    @property
    def plan(self) -> PlanRevision | None:
        return self.plans[-1] if self.plans else None

    @model_validator(mode="after")
    def references(self) -> Self:
        if (
            self.run.task_id != self.task.id
            or self.run.task_revision != self.task.revision
        ):
            raise ValueError("run must reference current task")
        if [t.revision for t in self.tasks] != list(range(1, len(self.tasks) + 1)):
            raise ValueError("task history must be consecutive")
        if any(t.id != self.task.id for t in self.tasks):
            raise ValueError("task identity is immutable")
        if [change.task_revision for change in self.task_changes] != list(
            range(2, len(self.tasks) + 1)
        ):
            raise ValueError("task revisions require consecutive change provenance")
        if self.run.snapshot_id != (self.snapshot.id if self.snapshot else None):
            raise ValueError("snapshot reference mismatch")
        if [p.revision for p in self.plans] != list(range(1, len(self.plans) + 1)):
            raise ValueError("plan history must be consecutive")
        collections: list[Sequence[RunEntity]] = [
            self.plans,
            self.claims,
            self.evidence,
            self.proposals,
            self.issues,
            self.decisions,
            self.tool_calls,
            self.model_calls,
            self.questions,
            self.validations,
            self.reservations,
        ]
        entities: list[RunEntity] = [
            entity for group in collections for entity in group
        ]
        unique(entities)
        if any(entity.run_id != self.run.id for entity in entities):
            raise ValueError("entity belongs to a different run")
        requirements = {r.id for task in self.tasks for r in task.requirements}
        current_requirements = {r.id for r in self.task.requirements}
        evidence = {e.id for e in self.evidence}
        tools = {t.id for t in self.tool_calls}
        tool_by_id = {t.id: t for t in self.tool_calls}
        claims = {c.id for c in self.claims}
        issues = {i.id for i in self.issues}
        steps = {s.id for p in self.plans for s in p.steps}

        def refs(values: list[str], allowed: set[str]) -> None:
            if not set(values) <= allowed:
                raise ValueError(f"unknown reference: {set(values) - allowed}")

        def snapshot_ref(value: str | None) -> None:
            if value is not None and value != self.run.snapshot_id:
                raise ValueError("entity snapshot does not match run")

        for plan in self.plans:
            if plan.requirements_revision > self.task.revision:
                raise ValueError("unknown requirements revision")
            snapshot_ref(plan.snapshot_id)
            if plan.snapshot_id != self.run.snapshot_id:
                raise ValueError("plan must reference run snapshot")
            plan_requirements = {
                r.id for r in self.tasks[plan.requirements_revision - 1].requirements
            }
            refs(plan.issues_addressed, issues)
            for step in plan.steps:
                refs(step.requirement_ids, plan_requirements)
                refs(step.evidence_ids, evidence)
            for decision in plan.decisions:
                if decision.run_id != self.run.id:
                    raise ValueError("decision belongs to another run")
                refs(decision.evidence_ids, evidence)
                refs(decision.related_issues, issues)
        for claim in self.claims:
            snapshot_ref(claim.snapshot_id)
            refs(claim.evidence_ids, evidence)
        for item in self.evidence:
            snapshot_ref(item.snapshot_id)
            refs([item.tool_call_id] if item.tool_call_id else [], tools)
            if item.status != ValidationStatus.NOT_RUN:
                assert item.tool_call_id is not None
                tool = tool_by_id[item.tool_call_id]
                if tool.finished_at is None or (
                    item.status == ValidationStatus.PASS and tool.exit_code != 0
                ):
                    raise ValueError(
                        "evidence status requires a completed matching tool result"
                    )
        for tool in self.tool_calls:
            snapshot_ref(tool.snapshot_id)
        for proposal in self.proposals:
            if proposal.base_revision > len(self.plans):
                raise ValueError("unknown proposal base revision")
            refs(proposal.claim_ids, claims)
            refs(list(proposal.requirement_coverage), current_requirements)
        for issue in self.issues:
            if issue.based_on_revision > len(self.plans):
                raise ValueError("unknown issue base revision")
            refs(issue.requirement_ids, requirements)
            refs(issue.evidence_ids, evidence)
            refs(
                [issue.duplicate_of] if issue.duplicate_of else [], issues - {issue.id}
            )
            if issue.resolution:
                refs(issue.resolution.evidence_ids, evidence)
                if (
                    issue.resolution.reviewed_revision
                    and issue.resolution.reviewed_revision > len(self.plans)
                ):
                    raise ValueError("unknown reviewed revision")
        for decision in self.decisions:
            refs(decision.evidence_ids, evidence)
            refs(decision.related_issues, issues)
        for question in self.questions:
            refs(question.requirement_ids, requirements)
        for validation in self.validations:
            refs(validation.requirement_ids, requirements)
            refs(validation.step_ids, steps)
            refs(validation.evidence_ids, evidence)
            refs([validation.tool_call_id] if validation.tool_call_id else [], tools)
            if validation.status != ValidationStatus.NOT_RUN:
                assert validation.tool_call_id is not None
                tool = tool_by_id[validation.tool_call_id]
                if tool.finished_at is None or validation.exit_code != tool.exit_code:
                    raise ValueError("validation must match a completed tool call")
        return self
