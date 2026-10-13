"""Test suite for Phase 2 [E]: Design artifacts + mode 'design'."""

import pytest
from pydantic import ValidationError

from astra_multi.agents.roles import (
    ContextBundle,
    DesignArtifactDraft,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
    format_propose_prompt,
    format_review_prompt,
    format_synthesize_prompt,
)
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    DesignArtifact,
    PlanRevision,
    PlanStep,
    Requirement,
    Run,
    RunPhase,
    RunState,
    TaskSpec,
)
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.quality_validator import (
    StructuralQualityValidator,
    ViolationSeverity,
)


def test_design_artifact_draft_schema():
    draft = DesignArtifactDraft(
        kind="state_machine",
        title="Agent Lifecycle State Machine",
        content="State transitions: INIT -> RUNNING -> FINAL",
        requirement_ids=["REQ-001"],
    )
    assert draft.kind == "state_machine"
    assert draft.requirement_ids == ["REQ-001"]

    # Must have at least 1 requirement_id
    with pytest.raises(ValidationError):
        DesignArtifactDraft(
            kind="state_machine",
            title="Empty reqs",
            content="content",
            requirement_ids=[],
        )

    # SynthesizerOutput accepts design_artifacts
    step = StepDraft(
        objective="Run verification tests",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["test_results.log"],
        completion_criteria=["All tests pass"],
    )
    synth = SynthesizerOutput(
        steps=[step],
        design_artifacts=[draft],
        rationale="Design covers core state machine",
    )
    assert len(synth.design_artifacts) == 1
    assert synth.design_artifacts[0].title == "Agent Lifecycle State Machine"


def test_design_mode_run_contract():
    task = TaskSpec(
        id="TASK-1",
        goal="Design Engine",
        requirements=[Requirement(id="REQ-001", text="Req 1", acceptance="Acc 1")],
    )
    run = Run(
        id="RUN-1",
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="design",
        config_hash="0" * 64,
    )
    assert run.mode == "design"

    # In design mode, snapshot_id must be None
    with pytest.raises(ValidationError):
        Run(
            id="RUN-1",
            task_id=task.id,
            task_revision=1,
            snapshot_id="SNAP-1",
            mode="design",
            config_hash="0" * 64,
        )


def test_quality_validator_rule_design_001_and_coverage():
    state = sample_state()
    # Update task to have 2 requirements: REQ-001 and REQ-002
    task = TaskSpec(
        id="TASK-1",
        goal="Design Task",
        requirements=[
            Requirement(id="REQ-001", text="Req 1", acceptance="Acc 1"),
            Requirement(id="REQ-002", text="Req 2", acceptance="Acc 2"),
        ],
    )
    run_design = Run(
        id=state.run.id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="design",
        config_hash="0" * 64,
    )

    # Step only covers REQ-001
    step = PlanStep(
        id="STEP-1",
        objective="Verify REQ-001",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["report.txt"],
        completion_criteria=["tests pass"],
    )

    # 1. In design mode, plan with NO design artifacts triggers RULE-DESIGN-001 blocker
    plan_no_artifacts = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
        design_artifacts=[],
    )
    state_no_artifacts = RunState(
        run=run_design,
        tasks=[task],
        plans=[plan_no_artifacts],
        snapshot=None,
    )

    validator = StructuralQualityValidator()
    report = validator.validate(state_no_artifacts)
    assert not report.passed
    design_violations = [v for v in report.violations if v.rule_id == "RULE-DESIGN-001"]
    assert len(design_violations) == 1
    assert design_violations[0].severity == ViolationSeverity.BLOCKER

    # 2. Plan with DesignArtifact covering REQ-002:
    # In design mode, RULE-COV-001 counts requirement_ids of design_artifacts!
    artifact = DesignArtifact(
        id="ART-1",
        kind="recovery_protocol",
        title="Crash Recovery Protocol",
        content="Resume from WAL checkpoint upon crash",
        requirement_ids=["REQ-002"],
    )
    plan_with_artifact = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
        design_artifacts=[artifact],
    )
    state_with_artifact = RunState(
        run=run_design,
        tasks=[task],
        plans=[plan_with_artifact],
        snapshot=None,
    )

    report_design = validator.validate(state_with_artifact)
    cov_violations = [v for v in report_design.violations if v.rule_id == "RULE-COV-001"]
    assert len(cov_violations) == 0, f"Expected REQ-002 to be covered by design artifact: {cov_violations}"
    assert not any(v.rule_id == "RULE-DESIGN-001" for v in report_design.violations)

    # In greenfield mode with same plan, REQ-002 is NOT covered by steps -> RULE-COV-001 fails
    run_greenfield = Run(
        id=state.run.id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="greenfield",
        config_hash="0" * 64,
    )
    state_greenfield = RunState(
        run=run_greenfield,
        tasks=[task],
        plans=[plan_with_artifact],
        snapshot=None,
    )
    report_gf = validator.validate(state_greenfield)
    gf_cov_violations = [v for v in report_gf.violations if v.rule_id == "RULE-COV-001"]
    assert len(gf_cov_violations) == 1
    assert "REQ-002" in gf_cov_violations[0].message


def test_exporter_design_artifacts_json_and_markdown():
    task = TaskSpec(
        id="TASK-1",
        goal="Design Engine Architecture",
        requirements=[Requirement(id="REQ-001", text="Req 1", acceptance="Acc 1")],
    )
    run = Run(
        id="RUN-1",
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="design",
        config_hash="0" * 64,
    )
    artifact = DesignArtifact(
        id="ART-1",
        kind="state_machine",
        title="Core State Machine",
        content="State transitions: IDLE -> ACTIVE -> DONE",
        requirement_ids=["REQ-001"],
    )
    step = PlanStep(
        id="STEP-1",
        objective="Verify state transitions",
        requirement_ids=["REQ-001"],
        validation="pytest",
        deliverables=["test.log"],
        completion_criteria=["tests pass"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id=run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
        design_artifacts=[artifact],
    )
    state = RunState(run=run, tasks=[task], plans=[plan], snapshot=None)

    exporter = PlanExporter()
    json_out = exporter.export_json(state)
    md_out = exporter.export_markdown(state)

    # JSON export contains design_artifacts
    assert "design_artifacts" in json_out
    assert len(json_out["design_artifacts"]) == 1
    assert json_out["design_artifacts"][0]["title"] == "Core State Machine"
    assert json_out["design_artifacts"][0]["kind"] == "state_machine"

    # Markdown export contains Section 4 Thiết kế
    assert "## 4. Thiết kế" in md_out
    assert "Core State Machine" in md_out
    assert "state_machine" in md_out
    assert "State transitions: IDLE -> ACTIVE -> DONE" in md_out


def test_prompt_rules_for_design_mode_and_propose_review():
    bundle = ContextBundle(
        run_id="RUN-1",
        snapshot_id=None,
        role="synthesizer",
        phase=RunPhase.REVISE,
        content="Test Context",
        source_ids=(),
        truncated_ids=(),
        omitted_ids=(),
        token_count=100,
        tokenizer="cl100k_base",
        omitted_repo_paths=(),
    )
    prop = ProposalOutput(
        approach="Cohesive technical design",
        requirement_coverage={"REQ-001": "Distributed Raft Consensus"},
    )
    rev = ReviewOutput(
        summary="Review summary",
        issues=[],
    )

    # format_synthesize_prompt in design mode
    msgs_design = format_synthesize_prompt(bundle, prop, rev, mode="design")
    system_design = msgs_design[0]["content"]
    assert "design_artifacts" in system_design
    assert "minimal" in system_design.lower() or "kiểm chứng" in system_design.lower()

    # format_synthesize_prompt in greenfield mode
    msgs_gf = format_synthesize_prompt(bundle, prop, rev, mode="greenfield")
    system_gf = msgs_gf[0]["content"]
    assert "actionable, step-by-step plan" in system_gf

    # format_propose_prompt contains mechanism rule
    prop_msgs = format_propose_prompt(bundle, [])
    prop_system = prop_msgs[0]["content"]
    assert "mechanism" in prop_system.lower() or "cơ chế" in prop_system.lower()

    # format_review_prompt includes requirement_coverage from proposal
    rev_msgs = format_review_prompt(bundle, prop)
    rev_user = rev_msgs[1]["content"]
    assert "Distributed Raft Consensus" in rev_user
