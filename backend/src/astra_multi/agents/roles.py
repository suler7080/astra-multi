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
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationInfo

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

    id: ID | None = Field(
        default=None,
        description="Deterministic issue ID (e.g. 'ISSUE-3a8c1f0d') when assigned",
    )
    claim: Text
    impact: Text
    severity: IssueSeverity = IssueSeverity.WARNING
    verification_request: Text | None = None
    suggested_resolution: Text
    requirement_ids: list[ID] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)


class IssueResolutionReport(AgentContract):
    """Reviewer evaluation/resolution for an existing issue."""

    issue_id: ID
    resolution_text: Text = "Resolved based on current plan revision"
    review_result: Literal["PASS", "FAIL", "DUPLICATE"] = "PASS"
    duplicate_of: ID | None = None
    review_note: Text = "Verified in plan revision"
    evidence_ids: list[ID] = Field(default_factory=list)


class RequirementVerdict(AgentContract):
    requirement_id: ID
    restated: Text
    mechanism: Text
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    gap: Text | None = None


class ReviewOutput(AgentContract):
    """Output schema for Reviewer in REVIEW phase."""

    issues: list[IssueReport] = Field(default_factory=list)
    summary: Text
    reviewed_evidence_ids: list[ID] = Field(default_factory=list)
    resolutions: list[IssueResolutionReport] = Field(default_factory=list)
    requirement_verdicts: list[RequirementVerdict] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_requirement_verdicts_coverage(self, info: ValidationInfo) -> Self:
        if info.context:
            expected_reqs = (
                info.context.get("expected_requirements")
                or info.context.get("requirements")
                or info.context.get("task_requirements")
            )
            if expected_reqs:
                expected_set = set(expected_reqs)
                provided_set = {v.requirement_id for v in self.requirement_verdicts}
                missing = expected_set - provided_set
                if missing:
                    raise ValueError(
                        f"ReviewOutput missing requirement verdicts for: {sorted(missing)}"
                    )
        return self


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
            raise ValueError("Step must explicitly map to at least one requirement ID")
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            if not res:
                raise ValueError("Step must explicitly map to at least one requirement ID")
            return res
        s = str(v).strip()
        if not s:
            raise ValueError("Step must explicitly map to at least one requirement ID")
        return [s]

    @field_validator("deliverables", mode="before")
    @classmethod
    def normalize_deliverables(cls, v: Any) -> list[str]:
        if not v:
            raise ValueError("Step must specify at least one deliverable")
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            if not res:
                raise ValueError("Step must specify at least one deliverable")
            return res
        s = str(v).strip()
        if not s:
            raise ValueError("Step must specify at least one deliverable")
        return [s]

    @field_validator("completion_criteria", mode="before")
    @classmethod
    def normalize_completion_criteria(cls, v: Any) -> list[str]:
        if not v:
            raise ValueError("Step must specify at least one completion criterion")
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            if not res:
                raise ValueError("Step must specify at least one completion criterion")
            return res
        s = str(v).strip()
        if not s:
            raise ValueError("Step must specify at least one completion criterion")
        return [s]


class DecisionDraft(AgentContract):
    question: Text
    chosen: Text
    rationale: Text
    alternatives: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    related_issue_ids: list[ID] = Field(default_factory=list)


class DesignArtifactDraft(AgentContract):
    kind: Literal[
        "state_machine",
        "message_schema",
        "stop_conditions",
        "recovery_protocol",
        "failure_modes",
        "sequence_flow",
    ]
    title: Text
    content: Text
    requirement_ids: list[ID] = Field(min_length=1)

    @field_validator("requirement_ids", mode="before")
    @classmethod
    def normalize_requirement_ids(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = [v]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            if not res:
                raise ValueError("Design artifact must specify at least one requirement_id")
            return res
        raise ValueError("requirement_ids must be a list of requirement IDs")


class SynthesizerOutput(AgentContract):
    """Output schema for Synthesizer in REVISE phase."""

    steps: list[StepDraft] = Field(min_length=1)
    decisions: list[DecisionDraft] = Field(default_factory=list)
    risks: list[Text] = Field(default_factory=list)
    issues_addressed: list[ID] = Field(default_factory=list)
    design_artifacts: list[DesignArtifactDraft] = Field(default_factory=list)
    rationale: Text

    @field_validator("issues_addressed", mode="before")
    @classmethod
    def normalize_issues_addressed(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("issues_addressed must be a list of issue IDs")
        cleaned: list[str] = []
        for idx, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(f"Issue ID at index {idx} must be a string, got {type(item).__name__}")
            s = item.strip()
            if not s:
                continue
            m = re.search(r"(ISSUE-[A-Za-z0-9_-]+)", s, re.IGNORECASE)
            if m:
                cleaned.append(m.group(1).rstrip(":.,; "))
            elif re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", s):
                cleaned.append(s.rstrip(":.,; "))
            else:
                raise ValueError(f"Invalid issue ID format in issues_addressed: '{item}'. Must not spoof IDs.")
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
    if '"plan":' in bundle.content:
        analyses_summary = [{"role": a.role, "findings": a.findings} for a in analyses]
    else:
        analyses_summary = [a.model_dump(mode="json") for a in analyses]
    system_message = (
        "You are the PLANNER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: PROPOSE\n"
        "Rules:\n"
        "1. Formulate a cohesive technical proposal covering all task requirements.\n"
        "2. Với mỗi requirement, nêu rõ cơ chế và vì sao cơ chế đó giải quyết đúng vấn đề của requirement.\n"
        "3. Synthesize findings, risks, and assumptions from earlier analyses.\n"
        "4. Output strictly according to ProposalOutput schema.\n"
        "5. Do not alter canonical run status or budget."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Independent Analyses:\n{json.dumps(analyses_summary, ensure_ascii=False, separators=(',', ': '))}\n\n"
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
        "1. Critique proposal/plan for feasibility, edge cases, and missing requirements.\n"
        "2. Với mỗi requirement, diễn đạt lại yêu cầu, chỉ ra cơ chế trong plan, rồi phán xét. Nếu cơ chế giải quyết vấn đề khác với requirement, kết luận FAIL và chỉ ra gap.\n"
        "3. For each issue, provide claim, impact, severity, and suggested resolution.\n"
        "4. Kiểm tra issue đã tồn tại trước khi tạo mới (tránh duplicate); nếu trùng, dùng review_result='DUPLICATE' và duplicate_of.\n"
        "5. Output strictly according to ReviewOutput schema, including requirement_verdicts."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal under review:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if current_plan and '"plan":' not in bundle.content:
        user_message += f"Current Plan:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
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
    mode: str = "greenfield",
) -> list[dict[str, str]]:
    """Prompt for Synthesizer in REVISE phase."""
    if mode == "design":
        rule1 = (
            "1. Formulate an architecture design consisting of design_artifacts (state_machine, message_schema, "
            "stop_conditions, recovery_protocol, failure_modes, sequence_flow) covering ALL task requirements. "
            "Steps must serve as a minimal implementation and verification plan (kế hoạch kiểm chứng/triển khai tối thiểu)."
        )
    else:
        rule1 = "1. Combine proposal, review feedback, and resolved issues into an actionable, step-by-step plan."

    system_message = (
        "You are the SYNTHESIZER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: REVISE\n"
        "Rules:\n"
        f"{rule1}\n"
        "2. Step dependencies must form a strict Directed Acyclic Graph (DAG).\n"
        "3. Every step must have objective, requirement_ids, validation, deliverables, and completion_criteria.\n"
        "4. In issues_addressed, list the exact issue IDs from Review Issues that this plan revision resolves (e.g. ['ISSUE-3a8c1f0d'] or []). Do NOT put sentences or descriptions into issues_addressed.\n"
        "5. Output strictly according to SynthesizerOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
        f"Review Issues:\n{json.dumps(review.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if current_plan and '"plan":' not in bundle.content:
        user_message += f"Current Plan Baseline:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
    user_message += "Please produce the synthesized revision."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def format_semantic_review_prompt(
    bundle: ContextBundle,
    current_plan: dict,
    open_issues: list[dict],
) -> list[dict[str, str]]:
    """Prompt for Reviewer in SEMANTIC_REVIEW phase."""
    system_message = (
        "You are the REVIEWER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: SEMANTIC_REVIEW\n"
        "Rules:\n"
        "1. Evaluate synthesized plan revision against previous issues and task requirements.\n"
        "2. Với mỗi requirement, diễn đạt lại yêu cầu, chỉ ra cơ chế trong plan, rồi phán xét. Nếu cơ chế giải quyết vấn đề khác với requirement, kết luận FAIL và chỉ ra gap.\n"
        "3. If an issue is addressed, produce a resolution with exact issue_id, review_result='PASS', review_note.\n"
        "4. Kiểm tra issue đã tồn tại trước khi tạo mới; nếu trùng (duplicate), dùng review_result='DUPLICATE' và duplicate_of.\n"
        "5. If new problems remain, report them as issues.\n"
        "6. Output strictly according to ReviewOutput schema, including requirement_verdicts."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Current Plan Revision to Evaluate:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if open_issues and '"open_issues":' not in bundle.content:
        user_message += f"Open Issues to evaluate:\n{json.dumps(open_issues, ensure_ascii=False, separators=(',', ': '))}\n\n"
    user_message += "Please provide your review, new issues (if any), and resolutions for addressed issues."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


