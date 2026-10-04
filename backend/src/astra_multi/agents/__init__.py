"""Agent role definitions and contracts."""

from astra_multi.agents.roles import (
    PROMPT_VERSION_V1,
    AgentContract,
    AnalysisFinding,
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
    format_independent_analysis_prompt,
    format_propose_prompt,
    format_review_prompt,
    format_synthesize_prompt,
)

__all__ = [
    "PROMPT_VERSION_V1",
    "AgentContract",
    "AnalysisFinding",
    "AnalysisOutput",
    "DecisionDraft",
    "IssueReport",
    "ProposalOutput",
    "ReviewOutput",
    "StepDraft",
    "SynthesizerOutput",
    "format_independent_analysis_prompt",
    "format_propose_prompt",
    "format_review_prompt",
    "format_synthesize_prompt",
]
