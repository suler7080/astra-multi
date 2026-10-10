"""Tests for FIX-03: Issue ID resolution and consistency across Reviewer, Synthesizer, and Domain.

Verifies:
1. Reviewer issues are enriched with deterministic domain issue IDs in review_out.issues.
2. Synthesizer prompts present exact issue IDs to the model.
3. Synthesizer can resolve issues using exact domain IDs or positional aliases (ISSUE-1, 1).
4. Semantic Reviewer can resolve issues using exact domain IDs or positional aliases.
5. Blocking issues properly transition to RESOLVED and allow runs to reach FINAL status.
6. Unresolved blocking issues fail quality gates and remain PARTIAL.
7. SynthesizerOutput validator robustly extracts issue IDs from free-form text.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from astra_multi.agents.roles import (
    AnalysisOutput,
    IssueReport,
    IssueResolutionReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
)
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    IssueSeverity,
    IssueStatus,
    RunStatus,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.schemas import ModelResult


def test_normalize_issues_addressed_regex_robustness():
    """Verify SynthesizerOutput normalizes exact IDs, aliases, and embedded strings."""
    # 1. Clean domain issue ID
    s1 = SynthesizerOutput(
        steps=[
            StepDraft(
                objective="Step 1",
                requirement_ids=["REQ-001"],
                deliverables=["doc"],
                completion_criteria=["done"],
                validation="pass",
            )
        ],
        rationale="test",
        issues_addressed=["ISSUE-3a8c1f0d"],
    )
    assert s1.issues_addressed == ["ISSUE-3a8c1f0d"]

    # 2. Issue ID embedded in text
    s2 = SynthesizerOutput(
        steps=[
            StepDraft(
                objective="Step 1",
                requirement_ids=["REQ-001"],
                deliverables=["doc"],
                completion_criteria=["done"],
                validation="pass",
            )
        ],
        rationale="test",
        issues_addressed=["ISSUE-3a8c1f0d: Mitigated SQL injection"],
    )
    assert s2.issues_addressed == ["ISSUE-3a8c1f0d"]

    # 3. Index alias embedded in text
    s3 = SynthesizerOutput(
        steps=[
            StepDraft(
                objective="Step 1",
                requirement_ids=["REQ-001"],
                deliverables=["doc"],
                completion_criteria=["done"],
                validation="pass",
            )
        ],
        rationale="test",
        issues_addressed=["Addressed issue ISSUE-1 in step 1"],
    )
    assert s3.issues_addressed == ["ISSUE-1"]

    # 4. Pure index alias and digit
    s4 = SynthesizerOutput(
        steps=[
            StepDraft(
                objective="Step 1",
                requirement_ids=["REQ-001"],
                deliverables=["doc"],
                completion_criteria=["done"],
                validation="pass",
            )
        ],
        rationale="test",
        issues_addressed=["ISSUE-1", "2"],
    )
    assert s4.issues_addressed == ["ISSUE-1", "2"]

    # 5. Fallback for completely unstructured string
    s5 = SynthesizerOutput(
        steps=[
            StepDraft(
                objective="Step 1",
                requirement_ids=["REQ-001"],
                deliverables=["doc"],
                completion_criteria=["done"],
                validation="pass",
            )
        ],
        rationale="test",
        issues_addressed=["general improvements"],
    )
    assert s5.issues_addressed == ["ISSUE-1"]


def test_fix03_issue_id_enrichment_and_exact_id_resolution():
    """Verify review_node enriches issue IDs and exact ID from prompt resolves blocking issue to FINAL."""
    issue_id_seen_by_synth: list[str] = []

    def mock_model_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role=role,
                findings=[f"Analysis by {role}"],
                marker="analysis",
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard proposal",
                requirement_coverage={"REQ-001": "Covered"},
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if not is_semantic:
                content = ReviewOutput(
                    summary="Review raised a blocking issue",
                    issues=[
                        IssueReport(
                            claim="Missing CSRF protection in form handling",
                            impact="Cross-site request forgery possible",
                            severity=IssueSeverity.BLOCKING,
                            suggested_resolution="Add CSRF tokens to form submission",
                            requirement_ids=["REQ-001"],
                        )
                    ],
                )
            else:
                target_id = issue_id_seen_by_synth[0] if issue_id_seen_by_synth else "ISSUE-UNKNOWN"
                content = ReviewOutput(
                    summary="Semantic review: verified CSRF token implementation",
                    resolutions=[
                        IssueResolutionReport(
                            issue_id=target_id,
                            resolution_text="CSRF token validation added in STEP-1",
                            review_result="PASS",
                            review_note="Verified against OWASP standards",
                        )
                    ],
                )
        elif output_schema == SynthesizerOutput:
            for m in messages:
                content_str = m.get("content", "")
                if "Review Issues:" in content_str:
                    idx = content_str.find("Review Issues:\n")
                    review_json_str = content_str[idx + len("Review Issues:\n"):].split("\n\n")[0]
                    try:
                        rev_data = json.loads(review_json_str)
                        if rev_data.get("issues"):
                            actual_id = rev_data["issues"][0].get("id")
                            if actual_id:
                                issue_id_seen_by_synth.append(actual_id)
                    except Exception:
                        pass

            addressed = [issue_id_seen_by_synth[0]] if issue_id_seen_by_synth else []
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Implement CSRF protection",
                        requirement_ids=["REQ-001"],
                        dependencies=[],
                        targets=["app/security.py"],
                        validation="pytest test_csrf.py passes",
                        deliverables=["CSRF middleware"],
                        completion_criteria=["Tokens validated"],
                    )
                ],
                decisions=[],
                risks=[],
                issues_addressed=addressed,
                rationale="Added CSRF tokens as requested",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"test-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix03.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="P4-quality-service", ttl=60)
            controller = WorkflowController(store, lease, actor="P4-quality-service")

            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=mock_model_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute full workflow
            final_res = app.invoke({"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []})

            # Verification 1: Synthesizer saw real enriched issue ID in its prompt
            assert len(issue_id_seen_by_synth) == 1
            assert issue_id_seen_by_synth[0].startswith("ISSUE-")

            # Verification 2: Run state domain issues
            final_state = store.load(state.run.id)
            assert len(final_state.issues) == 1
            domain_issue = final_state.issues[0]
            assert domain_issue.id == issue_id_seen_by_synth[0]
            assert domain_issue.status == IssueStatus.RESOLVED
            assert domain_issue.resolution is not None
            assert domain_issue.resolution.review_result == "PASS"

            # Verification 3: Plan revision contains real issue ID in issues_addressed
            assert final_state.plan is not None
            assert domain_issue.id in final_state.plan.issues_addressed

            # Verification 4: Gate passed and run reached FINAL status
            assert final_res.get("gate_passed") is True
            assert final_state.run.status == RunStatus.FINAL


def test_fix03_alias_resolution_for_index_based_llm():
    """Verify Synthesizer & Reviewer using positional aliases ('ISSUE-1') resolves domain issue."""
    def alias_model_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role=role,
                findings=[f"Analysis by {role}"],
                marker="analysis",
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard proposal",
                requirement_coverage={"REQ-001": "Covered"},
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if not is_semantic:
                content = ReviewOutput(
                    summary="Review raised a blocking issue",
                    issues=[
                        IssueReport(
                            claim="Hardcoded API credentials in configuration",
                            impact="Credential leakage",
                            severity=IssueSeverity.BLOCKING,
                            suggested_resolution="Use environment variables",
                            requirement_ids=["REQ-001"],
                        )
                    ],
                )
            else:
                # Semantic Reviewer uses positional alias 'ISSUE-1' instead of exact UUID!
                content = ReviewOutput(
                    summary="Semantic review: verified env var usage",
                    resolutions=[
                        IssueResolutionReport(
                            issue_id="ISSUE-1",  # Index alias!
                            resolution_text="Environment variables used in STEP-1",
                            review_result="PASS",
                            review_note="Verified in PlanRevision 1",
                        )
                    ],
                )
        elif output_schema == SynthesizerOutput:
            # Synthesizer uses positional alias 'ISSUE-1' instead of exact UUID!
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Load API keys from environment",
                        requirement_ids=["REQ-001"],
                        dependencies=[],
                        targets=["app/config.py"],
                        validation="pytest test_config.py passes",
                        deliverables=["Environment config loader"],
                        completion_criteria=["Keys loaded from os.environ"],
                    )
                ],
                decisions=[],
                risks=[],
                issues_addressed=["ISSUE-1"],  # Index alias!
                rationale="Used environment variables as requested",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"test-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix03_alias.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="P4-quality-service", ttl=60)
            controller = WorkflowController(store, lease, actor="P4-quality-service")

            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=alias_model_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            final_res = app.invoke({"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []})

            final_state = store.load(state.run.id)
            assert len(final_state.issues) == 1
            domain_issue = final_state.issues[0]
            # Verify alias was mapped to domain issue ID
            assert domain_issue.id.startswith("ISSUE-")
            assert domain_issue.status == IssueStatus.RESOLVED

            # Verify plan.issues_addressed contains domain ID, not 'ISSUE-1'
            assert final_state.plan is not None
            assert domain_issue.id in final_state.plan.issues_addressed
            assert "ISSUE-1" not in final_state.plan.issues_addressed

            # Verify quality gate passed and reached FINAL
            assert final_res.get("gate_passed") is True
            assert final_state.run.status == RunStatus.FINAL


def test_fix03_unresolved_blocking_issue_terminates_partial():
    """Verify run with unaddressed blocking issue fails quality gate and terminates PARTIAL."""
    def failing_model_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(
                role=role,
                findings=[f"Analysis by {role}"],
                marker="analysis",
            )
        elif output_schema == ProposalOutput:
            content = ProposalOutput(
                approach="Standard proposal",
                requirement_coverage={"REQ-001": "Covered"},
            )
        elif output_schema == ReviewOutput:
            is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
            if not is_semantic:
                content = ReviewOutput(
                    summary="Review raised a blocking issue",
                    issues=[
                        IssueReport(
                            claim="Critical SQL injection vulnerability",
                            impact="Full database compromise",
                            severity=IssueSeverity.BLOCKING,
                            suggested_resolution="Use parameterized queries",
                            requirement_ids=["REQ-001"],
                        )
                    ],
                    resolutions=[],
                )
            else:
                content = ReviewOutput(
                    summary="Semantic review: issue still not resolved",
                    issues=[],
                    resolutions=[],
                )
        elif output_schema == SynthesizerOutput:
            # Synthesizer completely ignores the issue!
            content = SynthesizerOutput(
                steps=[
                    StepDraft(
                        objective="Simple query",
                        requirement_ids=["REQ-001"],
                        dependencies=[],
                        targets=["db.py"],
                        validation="pytest passes",
                        deliverables=["db logic"],
                        completion_criteria=["queries run"],
                    )
                ],
                decisions=[],
                risks=[],
                issues_addressed=[],  # NOT addressed!
                rationale="Did not fix SQL injection",
            )
        else:
            content = "ok"

        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"test-{role}",
            provider="fake",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost_actual_usd=0.001,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix03_unresolved.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="P4-quality-service", ttl=60)
            controller = WorkflowController(store, lease, actor="P4-quality-service")

            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=failing_model_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute workflow for 1 round
            final_res = app.invoke({"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []})

            final_state = store.load(state.run.id)
            assert len(final_state.issues) == 1
            domain_issue = final_state.issues[0]
            # Issue remains OPEN
            assert domain_issue.status != IssueStatus.RESOLVED

            # Gate must fail due to unresolved blocking issues
            assert final_res.get("gate_passed") is False
            assert "unresolved blocking issues" in final_res.get("stop_reason", "")
            assert final_state.run.status == RunStatus.PARTIAL
