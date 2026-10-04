"""Unit tests for agents role prompts, output schemas, and isolation contracts (P3.2)."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from astra_multi.agents.roles import (
    AnalysisOutput,
    ProposalOutput,
    ReviewOutput,
    SynthesizerOutput,
    format_independent_analysis_prompt,
)
from astra_multi.context.bundle import ContextBuilder, ContextLimits
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import IssueSeverity, RunPhase
from astra_multi.persistence.artifacts import FileArtifactStore


def test_analysis_output_schema_validation():
    """Valid analysis passes schema."""
    valid = {
        "role": "planner",
        "findings": ["Found service architecture uses FastAPI"],
        "risks": ["Database locking during migration"],
        "assumptions": ["PostgreSQL 14+ is used"],
        "evidence_ids": ["EVID-01"],
        "marker": "test-marker-1",
    }
    obj = AnalysisOutput.model_validate(valid)
    assert obj.role == "planner"
    assert len(obj.findings) == 1
    assert obj.marker == "test-marker-1"


def test_schema_forbids_budget_or_routing_tampering():
    """Output schemas forbid unexpected fields such as budget or routing overrides."""
    tampered_data = {
        "role": "planner",
        "findings": ["Everything looks fine"],
        "budget": {"override_limit": 100000},  # Not allowed!
        "routing": "DIRECT_TO_EXPORT",  # Not allowed!
    }
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(tampered_data)


def test_proposal_output_schema():
    """Proposal requires valid coverage and approach."""
    valid_proposal = {
        "approach": "Incremental microservices migration",
        "alternatives": ["Monolith rewrite"],
        "tradeoffs": ["High network overhead"],
        "requirement_coverage": {"REQ-001": "Full coverage via proxy"},
        "claim_ids": ["CLAIM-01"],
    }
    prop = ProposalOutput.model_validate(valid_proposal)
    assert prop.approach.startswith("Incremental")
    assert "REQ-001" in prop.requirement_coverage


def test_review_output_schema_and_issue_validation():
    """Review output must contain issues with severity and basis."""
    review_data = {
        "summary": "Review complete with 1 blocker",
        "reviewed_evidence_ids": ["EVID-01"],
        "issues": [
            {
                "claim": "Migration lacks rollback step",
                "impact": "Data inconsistency if migration fails",
                "severity": "blocking",
                "suggested_resolution": "Add rollback migration step",
                "requirement_ids": ["REQ-001"],
                "evidence_ids": ["EVID-01"],
            }
        ],
    }
    review = ReviewOutput.model_validate(review_data)
    assert len(review.issues) == 1
    assert review.issues[0].severity == IssueSeverity.BLOCKING


def test_synthesizer_output_schema():
    """Synthesizer output must satisfy step drafts."""
    synth_data = {
        "steps": [
            {
                "objective": "Setup schema migration tool",
                "requirement_ids": ["REQ-001"],
                "dependencies": [],
                "validation": "pytest tests/test_migrations.py passes",
                "deliverables": ["alembic.ini"],
                "completion_criteria": ["Database schema matches v2"],
            }
        ],
        "decisions": [
            {
                "question": "Which migration tool to use?",
                "chosen": "Alembic",
                "rationale": "Standard for SQLAlchemy",
                "alternatives": ["yoyo"],
            }
        ],
        "risks": ["Migration timeout"],
        "issues_addressed": ["ISSUE-01"],
        "rationale": "Alembic provides robust downgrade support.",
    }
    synth = SynthesizerOutput.model_validate(synth_data)
    assert len(synth.steps) == 1
    assert synth.steps[0].objective == "Setup schema migration tool"


def test_independent_analysis_context_isolation():
    """In INDEPENDENT_ANALYSIS phase, context builder does not expose peer outputs or plan."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts = FileArtifactStore(Path(tmpdir))
        builder = ContextBuilder(artifacts)
        state = sample_state(repo=True)

        planner_bundle = builder.build_context(
            run=state,
            role="planner",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=ContextLimits(max_tokens=4000),
        )
        reviewer_bundle = builder.build_context(
            run=state,
            role="reviewer",
            phase=RunPhase.INDEPENDENT_ANALYSIS,
            refs=[],
            limits=ContextLimits(max_tokens=4000),
        )

        # Neither bundle contains peer outputs or prior plan
        assert "plan" not in planner_bundle.content
        assert "open_issues" not in planner_bundle.content
        assert "plan" not in reviewer_bundle.content
        assert "open_issues" not in reviewer_bundle.content

        # Formatting prompts produces valid messages
        planner_messages = format_independent_analysis_prompt(planner_bundle)
        assert any("INDEPENDENT_ANALYSIS" in m["content"] for m in planner_messages)
        assert any("v1.0" in m["content"] for m in planner_messages)
