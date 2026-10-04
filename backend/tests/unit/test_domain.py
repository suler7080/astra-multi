import importlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from astra_multi.domain import models
from astra_multi.domain.commands import (
    AddRecord,
    AnswerQuestion,
    ChangeIssue,
    CommitPlan,
    ReviseTask,
    TransitionRun,
)
from astra_multi.domain.export_contracts import CONTRACTS, invalid_samples, samples
from astra_multi.domain.fixtures import sample_issue, sample_plan, sample_state
from astra_multi.domain.models import (
    BudgetReservation,
    Claim,
    Decision,
    Evidence,
    IssueResolution,
    IssueSeverity,
    IssueStatus,
    ModelCall,
    Question,
    Requirement,
    RequirementChange,
    Run,
    RunPhase,
    RunState,
    RunStatus,
    TaskSpec,
    ToolCall,
    ValidationResult,
    ValidationStatus,
    utc_now,
)
from astra_multi.domain.policies import (
    ISSUE_TRANSITIONS,
    PHASE_TRANSITIONS,
    InvalidState,
    RevisionConflict,
    apply_mutation,
)


def command_args(state):
    return dict(
        expected_revision=state.run.revision,
        node="test",
        logical_operation_id=f"op-{state.run.revision}",
        actor="controller",
    )


def mutate(state, command):
    return apply_mutation(state, command, utc_now())[0]


@pytest.mark.parametrize("repo", [False, True])
def test_repo_and_greenfield_round_trip(repo):
    state = sample_state(repo=repo)
    assert RunState.model_validate_json(state.model_dump_json()) == state
    assert state.run.snapshot_id == (state.snapshot.id if repo else None)


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"mode": "unknown"},
        {"phase": "FINAL"},
        {"status": "COMPLETED"},
        {"revision": 0},
        {"revision": "1"},
        {"schema_version": 2},
        {"snapshot_id": "SNAP-001"},
        {"mode": "repo"},
        {"config_hash": "bad"},
        {"extra": "not allowed"},
        {"created_at": "2026-10-02T00:00:00"},
    ],
)
def test_invalid_run_payloads(change):
    payload = sample_state().run.model_dump(mode="json")
    payload.update(change)
    with pytest.raises(ValidationError):
        Run.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["id", "task_id", "snapshot_id", "mode", "config_hash", "task_revision"]
)
def test_required_run_fields(field):
    payload = sample_state().run.model_dump(mode="json")
    del payload[field]
    with pytest.raises(ValidationError):
        Run.model_validate(payload)


def test_utc_normalization():
    created = datetime(2026, 10, 2, 12, tzinfo=timezone(timedelta(hours=7)))
    requirement = Requirement(
        id="REQ", text="Health", acceptance="200", created_at=created
    )
    assert requirement.created_at.hour == 5
    assert requirement.created_at.utcoffset() == timedelta(0)


def test_task_rejects_duplicates_and_blank_text():
    task = sample_state().task
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(
            {**task.model_dump(), "requirements": [task.requirements[0]] * 2}
        )
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({**task.model_dump(), "goal": "  "})


def test_all_records_round_trip_and_resolve_references():
    state = sample_state(repo=True)
    common = dict(run_id=state.run.id)
    artifact = models.ArtifactRef(content_hash="a" * 64, size=3)
    records = [
        ToolCall(
            id="TOOL",
            **common,
            request_hash="b" * 64,
            arguments_redacted={"path": "app.py"},
            environment="sandbox",
            snapshot_id=state.run.snapshot_id,
            exit_code=0,
            output_artifact=artifact,
            started_at=utc_now(),
            finished_at=utc_now(),
        ),
        Evidence(
            id="EVID",
            **common,
            source_type="tool",
            locator="TOOL",
            content_hash="a" * 64,
            captured_at=utc_now(),
            snapshot_id=state.run.snapshot_id,
            tool_call_id="TOOL",
            status=ValidationStatus.PASS,
            artifact=artifact,
        ),
        Claim(
            id="CLAIM",
            **common,
            text="Test ran",
            kind="fact",
            evidence_ids=["EVID"],
            snapshot_id=state.run.snapshot_id,
        ),
        models.Proposal(
            id="PROP",
            **common,
            author_role="planner",
            base_revision=0,
            approach="HTTP route",
            claim_ids=["CLAIM"],
        ),
        sample_issue(state),
        Decision(
            id="DEC",
            **common,
            question="Protocol?",
            chosen="HTTP",
            rationale="Interoperability",
            evidence_ids=["EVID"],
            related_issues=["ISSUE-001"],
        ),
        ModelCall(
            id="MODEL",
            **common,
            role="planner",
            provider="fake",
            model_id="fake-1",
            prompt_version="1",
            input_hash="c" * 64,
            usage={"input": 12},
        ),
        Question(
            id="QUESTION",
            **common,
            text="Is auth required?",
            requirement_ids=["REQ-001"],
        ),
        BudgetReservation(
            id="BUDGET", **common, operation_id="model-op", tokens=12, cost=0.01
        ),
    ]
    for record in records:
        assert type(record).model_validate_json(record.model_dump_json()) == record
        state = mutate(state, AddRecord(**command_args(state), record=record))
    state = mutate(state, CommitPlan(**command_args(state), plan=sample_plan(state)))
    validation = ValidationResult(
        id="VALID",
        **common,
        expected="200",
        actual="200",
        exit_code=0,
        executed_at=utc_now(),
        tool_call_id="TOOL",
        status=ValidationStatus.PASS,
        evidence_ids=["EVID"],
        requirement_ids=["REQ-001"],
        step_ids=["STEP-001"],
    )
    state = mutate(state, AddRecord(**command_args(state), record=validation))
    assert RunState.model_validate_json(state.model_dump_json()) == state


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "PASS"},
        {"status": "FAIL"},
        {"status": "NOT_RUN", "exit_code": 0},
        {
            "status": "PASS",
            "actual": "failure",
            "exit_code": 1,
            "tool_call_id": "TOOL",
            "executed_at": utc_now(),
        },
    ],
)
def test_validation_never_passes_without_execution(payload):
    with pytest.raises(ValidationError):
        ValidationResult(id="VAL", run_id="RUN", expected="200", **payload)


@pytest.mark.parametrize(
    "record",
    [
        Claim(
            id="CLAIM",
            run_id="RUN-001",
            text="x",
            kind="fact",
            evidence_ids=["missing"],
            snapshot_id=None,
        ),
        Claim(id="CLAIM", run_id="other", text="x", kind="fact", snapshot_id=None),
        Claim(id="CLAIM", run_id="RUN-001", text="x", kind="fact", snapshot_id="other"),
        Question(
            id="QUESTION", run_id="RUN-001", text="x", requirement_ids=["missing"]
        ),
    ],
)
def test_unknown_cross_run_and_snapshot_references_rejected(record):
    state = sample_state()
    with pytest.raises(ValidationError):
        mutate(state, AddRecord(**command_args(state), record=record))


def test_plan_dependency_validation():
    plan = sample_plan(sample_state())
    payload = plan.model_dump()
    payload["steps"][0]["dependencies"] = ["STEP-001"]
    with pytest.raises(ValidationError, match="cycle"):
        models.PlanRevision.model_validate(payload)
    payload["steps"][0]["dependencies"] = ["missing"]
    with pytest.raises(ValidationError, match="dependency"):
        models.PlanRevision.model_validate(payload)


@pytest.mark.parametrize("source", list(RunPhase))
@pytest.mark.parametrize("target", list(RunPhase))
def test_phase_transition_table(source, target):
    state = sample_state()
    state = state.model_copy(
        update={"run": state.run.model_copy(update={"phase": source})}
    )
    command = TransitionRun(
        **command_args(state), phase=target, status=RunStatus.RUNNING
    )
    if target in PHASE_TRANSITIONS[source]:
        assert mutate(state, command).run.phase == target
    else:
        with pytest.raises(InvalidState):
            mutate(state, command)


@pytest.mark.parametrize(
    "status",
    [RunStatus.FINAL, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED],
)
def test_terminal_runs_cannot_resume(status):
    state = sample_state()
    state = state.model_copy(
        update={
            "run": state.run.model_copy(
                update={"status": status, "stop_reason": "done"}
            )
        }
    )
    with pytest.raises(InvalidState, match="terminal"):
        mutate(
            state,
            TransitionRun(
                **command_args(state), phase=RunPhase.INTAKE, status=RunStatus.RUNNING
            ),
        )


def test_final_reserved_for_quality_service_and_stale_revision_rejected():
    state = sample_state()
    with pytest.raises(InvalidState, match="P4"):
        mutate(
            state,
            TransitionRun(
                **command_args(state), phase=RunPhase.EXPORT, status=RunStatus.FINAL
            ),
        )
    with pytest.raises(RevisionConflict):
        mutate(
            state,
            CommitPlan(
                **{**command_args(state), "expected_revision": 2},
                plan=sample_plan(state),
            ),
        )


def issue_state():
    state = sample_state()
    return mutate(state, AddRecord(**command_args(state), record=sample_issue(state)))


def resolution():
    return IssueResolution(
        text="Specify health failure",
        reviewed_revision=1,
        reviewer="reviewer",
        review_result="PASS",
        review_note="Checked new candidate",
    )


def advance_issue(state, status, **kwargs):
    return mutate(
        state,
        ChangeIssue(
            **command_args(state),
            issue_id="ISSUE-001",
            status=status,
            reason="review",
            **kwargs,
        ),
    )


def test_resolution_requires_new_revision_and_keeps_history():
    state = issue_state()
    state = advance_issue(state, IssueStatus.INVESTIGATING)
    state = advance_issue(
        state,
        IssueStatus.PROPOSED_RESOLUTION,
        resolution=IssueResolution(text="Candidate"),
    )
    with pytest.raises(InvalidState, match="new current plan"):
        advance_issue(state, IssueStatus.RESOLVED, resolution=resolution())
    state = mutate(state, CommitPlan(**command_args(state), plan=sample_plan(state)))
    state = advance_issue(state, IssueStatus.RESOLVED, resolution=resolution())
    assert [h.status for h in state.issues[0].history] == [
        IssueStatus.OPEN,
        IssueStatus.INVESTIGATING,
        IssueStatus.PROPOSED_RESOLUTION,
        IssueStatus.RESOLVED,
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"reviewer": None},
        {"reviewer": "controller"},
        {"review_result": "FAIL"},
        {"review_note": None},
    ],
)
def test_empty_consensus_and_self_review_cannot_close_blocker(change):
    state = issue_state()
    state = advance_issue(state, IssueStatus.INVESTIGATING)
    state = advance_issue(
        state,
        IssueStatus.PROPOSED_RESOLUTION,
        resolution=IssueResolution(text="Candidate"),
    )
    state = mutate(state, CommitPlan(**command_args(state), plan=sample_plan(state)))
    with pytest.raises(InvalidState):
        advance_issue(
            state,
            IssueStatus.RESOLVED,
            resolution=IssueResolution.model_validate(
                {**resolution().model_dump(), **change}
            ),
        )


@pytest.mark.parametrize("source", list(IssueStatus))
@pytest.mark.parametrize("target", list(IssueStatus))
def test_issue_transition_table(source, target):
    state = issue_state()
    issue = state.issues[0].model_copy(
        update={"severity": IssueSeverity.WARNING, "status": source}
    )
    state = state.model_copy(
        update={"issues": [issue, sample_issue(state, "ISSUE-002")]}
    )
    kwargs = (
        {"resolution": IssueResolution(text="Reasoned response")}
        if target
        in {IssueStatus.PROPOSED_RESOLUTION, IssueStatus.RESOLVED, IssueStatus.REJECTED}
        else {}
    )
    if target == IssueStatus.DUPLICATE:
        kwargs["duplicate_of"] = "ISSUE-002"
    if target in ISSUE_TRANSITIONS[source]:
        assert advance_issue(state, target, **kwargs).issues[0].status == target
    else:
        with pytest.raises(InvalidState):
            advance_issue(state, target, **kwargs)


def test_duplicate_has_valid_target_and_cannot_lower_blocker():
    state = issue_state()
    for target in ("ISSUE-001", "missing"):
        with pytest.raises(InvalidState):
            advance_issue(state, IssueStatus.DUPLICATE, duplicate_of=target)
    warning = sample_issue(state, "ISSUE-002").model_copy(
        update={"severity": IssueSeverity.WARNING}
    )
    state = mutate(state, AddRecord(**command_args(state), record=warning))
    with pytest.raises(InvalidState, match="blocking target"):
        advance_issue(state, IssueStatus.DUPLICATE, duplicate_of=warning.id)


def test_requirement_change_requires_persisted_provenance():
    state = issue_state()
    task = state.task.model_copy(
        update={
            "revision": 2,
            "requirements": [
                Requirement(
                    id="REQ-001", text="Changed health policy", acceptance="200 or 503"
                )
            ],
        }
    )
    state = mutate(
        state,
        ReviseTask(
            **command_args(state), task=task, reason="User changed health contract"
        ),
    )
    forged = RequirementChange(task_revision=2, actor="user", reason="Not persisted")
    with pytest.raises(InvalidState):
        advance_issue(
            state,
            IssueStatus.REJECTED,
            resolution=IssueResolution(
                text="No longer applies", requirement_change=forged
            ),
        )
    state = advance_issue(
        state,
        IssueStatus.REJECTED,
        resolution=IssueResolution(
            text="Requirement superseded", requirement_change=state.task_changes[0]
        ),
    )
    assert state.issues[0].resolution.requirement_change == state.task_changes[0]
    assert len(state.tasks) == 2


def test_waiting_questions_and_answer_revision():
    state = sample_state()
    state = mutate(
        state,
        AddRecord(
            **command_args(state),
            record=Question(id="Q", run_id=state.run.id, text="Auth?"),
        ),
    )
    state = mutate(
        state,
        TransitionRun(
            **command_args(state),
            phase=state.run.phase,
            status=RunStatus.WAITING_FOR_INPUT,
        ),
    )
    resume = TransitionRun(
        **command_args(state), phase=state.run.phase, status=RunStatus.RUNNING
    )
    with pytest.raises(InvalidState):
        mutate(state, resume)
    state = mutate(
        state, AnswerQuestion(**command_args(state), question_id="Q", answer="No")
    )
    with pytest.raises(RevisionConflict):
        mutate(state, resume)
    state = mutate(
        state,
        TransitionRun(
            **command_args(state), phase=state.run.phase, status=RunStatus.RUNNING
        ),
    )
    assert state.questions[0].answered_by == "controller"


def test_domain_import_does_not_load_framework_or_sdks():
    importlib.import_module("astra_multi.domain.repositories")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import astra_multi.domain.models; import astra_multi.domain.policies; import astra_multi.domain.repositories; assert not any(m.split('.')[0] in {'langgraph', 'langchain_core', 'openai', 'google'} for m in sys.modules)",
        ],
        check=True,
    )


def test_exported_samples_validate_and_cover_all_contracts():
    fixtures = samples()
    assert {contract.__name__ for contract in CONTRACTS} <= fixtures.keys()
    for fixture in fixtures.values():
        assert type(fixture).model_validate_json(fixture.model_dump_json()) == fixture
    for payload in invalid_samples().values():
        with pytest.raises(ValidationError):
            Run.model_validate(payload)


def test_validation_cannot_reference_an_unfinished_tool():
    state = sample_state()
    tool = ToolCall(
        id="TOOL",
        run_id=state.run.id,
        request_hash="a" * 64,
        arguments_redacted={},
        environment="sandbox",
        snapshot_id=None,
        exit_code=None,
        output_artifact=None,
        started_at=utc_now(),
        finished_at=None,
    )
    state = mutate(state, AddRecord(**command_args(state), record=tool))
    validation = ValidationResult(
        id="VALID",
        run_id=state.run.id,
        status=ValidationStatus.PASS,
        expected="200",
        actual="200",
        exit_code=0,
        tool_call_id=tool.id,
        executed_at=utc_now(),
    )
    with pytest.raises(ValidationError, match="completed tool call"):
        mutate(state, AddRecord(**command_args(state), record=validation))
