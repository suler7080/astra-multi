"""Role definitions, versioned prompt templates, and output schemas for Astra Multi agents.

P3.2 Role prompts and context contracts:
- Roles: Planner, Reviewer, Synthesizer.
- Strict Pydantic output schemas (prevent changing budget/routing permissions).
- Context isolation: In INDEPENDENT_ANALYSIS, peer outputs are omitted.
- Contract adherence: Proposals/deltas only; no direct mutation of canonical state.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from astra_multi.context.bundle import ContextBundle
from astra_multi.domain.models import (
    ID,
    IssueSeverity,
    Text,
)


class AgentContract(BaseModel):
    """Base schema for agent outputs. Forbids extra fields like routing/budget overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# -----------------------------------------------------------------------------
# Output Schemas for each role and phase
# -----------------------------------------------------------------------------


class AnalysisFinding(AgentContract):
    finding: Text
    evidence_ids: list[ID] = Field(default_factory=list)


class AnalysisOutput(AgentContract):
    """Output schema for INDEPENDENT_ANALYSIS phase."""

    role: Literal["planner", "reviewer"]
    findings: list[Text] = Field(min_length=1)
    risks: list[Text] = Field(default_factory=list)
    assumptions: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    marker: str = ""  # Used for testing isolation


class ProposalOutput(AgentContract):
    """Output schema for Planner in PROPOSE phase."""

    approach: Text
    alternatives: list[Text] = Field(default_factory=list)
    tradeoffs: list[Text] = Field(default_factory=list)
    requirement_coverage: dict[ID, Text] = Field(
        default_factory=dict,
        description="Map from requirement ID to description of how it is addressed",
    )
    claim_ids: list[ID] = Field(
        default_factory=list,
        description="IDs of established domain claims (CLAIM-...) if any. Leave empty if none.",
    )


class IssueReport(AgentContract):
    """An issue raised by Reviewer in REVIEW phase."""

    claim: Text
    impact: Text
    severity: IssueSeverity = IssueSeverity.WARNING
    verification_request: Text | None = None
    suggested_resolution: Text
    requirement_ids: list[ID] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)


class ReviewOutput(AgentContract):
    """Output schema for Reviewer in REVIEW phase."""

    issues: list[IssueReport] = Field(default_factory=list)
    summary: Text
    reviewed_evidence_ids: list[ID] = Field(default_factory=list)


class StepDraft(AgentContract):
    objective: Text
    requirement_ids: list[ID] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    targets: list[Text] = Field(default_factory=list)
    validation: Text
    deliverables: list[Text] = Field(min_length=1)
    completion_criteria: list[Text] = Field(min_length=1)
    evidence_ids: list[ID] = Field(default_factory=list)

    @field_validator("requirement_ids", mode="before")
    @classmethod
    def normalize_requirement_ids(cls, v: Any) -> list[str]:
        if not v:
            return ["REQ-001"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["REQ-001"]
        return [str(v).strip()]

    @field_validator("deliverables", mode="before")
    @classmethod
    def normalize_deliverables(cls, v: Any) -> list[str]:
        if not v:
            return ["Deliverable artifact"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["Deliverable artifact"]
        return [str(v).strip()]

    @field_validator("completion_criteria", mode="before")
    @classmethod
    def normalize_completion_criteria(cls, v: Any) -> list[str]:
        if not v:
            return ["Completion verified"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["Completion verified"]
        return [str(v).strip()]


class DecisionDraft(AgentContract):
    question: Text
    chosen: Text
    rationale: Text
    alternatives: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    related_issue_ids: list[ID] = Field(default_factory=list)


class SynthesizerOutput(AgentContract):
    """Output schema for Synthesizer in REVISE phase."""

    steps: list[StepDraft] = Field(min_length=1)
    decisions: list[DecisionDraft] = Field(default_factory=list)
    risks: list[Text] = Field(default_factory=list)
    issues_addressed: list[ID] = Field(default_factory=list)
    rationale: Text

    @field_validator("issues_addressed", mode="before")
    @classmethod
    def normalize_issues_addressed(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        cleaned: list[str] = []
        for idx, item in enumerate(v):
            if not isinstance(item, str):
                continue
            s = item.strip()
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", s):
                cleaned.append(s)
            else:
                cleaned.append(f"ISSUE-{idx + 1}")
        return cleaned


# -----------------------------------------------------------------------------
# Versioned Prompt Templates
# -----------------------------------------------------------------------------

PROMPT_VERSION_V1 = "v1.0"


def format_independent_analysis_prompt(bundle: ContextBundle) -> list[dict[str, str]]:
    """Prompt for independent analysis.

    Ensures prompt version and instructions enforce clean fact collection and isolation.
    """
    system_message = (
        f"You are the {bundle.role.upper()} in the Astra Multi architecture design system.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: INDEPENDENT_ANALYSIS\n"
        "Rules:\n"
        "1. Perform independent technical analysis based ONLY on the provided task and snapshot evidence.\n"
        "2. Do not assume any decisions from other peers.\n"
        "3. Output strictly according to the specified AnalysisOutput schema.\n"
        "4. You do not have permissions to modify budget, execution routing, or system state."
    )
    user_message = f"Context:\n{bundle.content}\n\nPlease perform your independent analysis."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def format_propose_prompt(bundle: ContextBundle, analyses: list[AnalysisOutput]) -> list[dict[str, str]]:
    """Prompt for Planner in PROPOSE phase."""
    analyses_summary = [a.model_dump(mode="json") for a in analyses]
    system_message = (
        "You are the PLANNER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: PROPOSE\n"
        "Rules:\n"
        "1. Formulate a cohesive technical proposal covering all task requirements.\n"
        "2. Synthesize findings, risks, and assumptions from earlier analyses.\n"
        "3. Output strictly according to ProposalOutput schema.\n"
        "4. Do not alter canonical run status or budget."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Independent Analyses:\n{json.dumps(analyses_summary, ensure_ascii=False, indent=2)}\n\n"
        "Please generate your proposal."
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def format_review_prompt(
    bundle: ContextBundle,
    proposal: ProposalOutput,
    current_plan: dict | None = None,
) -> list[dict[str, str]]:
    """Prompt for Reviewer in REVIEW phase."""
    system_message = (
        "You are the REVIEWER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: REVIEW\n"
        "Rules:\n"
        "1. Rigorously critique the proposal and/or plan for technical feasibility, edge cases, and missing requirements.\n"
        "2. For each identified issue, provide a claim, impact, severity (blocking/warning/info), and suggested resolution.\n"
        "3. Issues must link to evidence or request verification.\n"
        "4. Output strictly according to ReviewOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal under review:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
    )
    if current_plan:
        user_message += f"Current Plan:\n{json.dumps(current_plan, ensure_ascii=False, indent=2)}\n\n"
    user_message += "Please provide your review and issues."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def format_synthesize_prompt(
    bundle: ContextBundle,
    proposal: ProposalOutput,
    review: ReviewOutput,
    current_plan: dict | None = None,
) -> list[dict[str, str]]:
    """Prompt for Synthesizer in REVISE phase."""
    system_message = (
        "You are the SYNTHESIZER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: REVISE\n"
        "Rules:\n"
        "1. Combine proposal, review feedback, and resolved issues into an actionable, step-by-step plan.\n"
        "2. Step dependencies must form a strict Directed Acyclic Graph (DAG).\n"
        "3. Every step must have objective, requirement_ids, validation, deliverables, and completion_criteria.\n"
        "4. In issues_addressed, list only issue IDs (e.g. ['ISSUE-1', 'ISSUE-2'] or []). Do NOT put sentences or descriptions into issues_addressed.\n"
        "5. Output strictly according to SynthesizerOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
        f"Review Issues:\n{json.dumps(review.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
    )
    if current_plan:
        user_message += f"Current Plan Baseline:\n{json.dumps(current_plan, ensure_ascii=False, indent=2)}\n\n"
    user_message += "Please produce the synthesized revision."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
