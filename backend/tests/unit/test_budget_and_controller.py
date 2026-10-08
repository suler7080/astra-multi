"""Unit tests for budget service, stagnation detector, and controller (P3.3 & P3.4)."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import Issue, IssueSeverity, RunPhase
from astra_multi.orchestration.budget import BudgetExhaustedError, BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.sqlite import SQLiteStore


def test_budget_service_atomic_reservation_and_settlement():
    budget = BudgetService(token_limit=1000, cost_limit=1.0, call_limit=5)

    # Make reservation
    op1 = budget.reserve(estimated_tokens=400, estimated_cost=0.4)
    assert budget.total_reserved_tokens == 400
    assert budget.total_reserved_cost == 0.4

    # Settle reservation
    budget.settle(op1, actual_tokens=350, actual_cost=0.35)
    assert budget.total_reserved_tokens == 0
    summary = budget.get_summary()
    assert summary["used_tokens"] == 350
    assert summary["used_cost"] == 0.35
    assert summary["settled_calls"] == 1


def test_budget_service_blocks_when_exceeding_token_limit():
    budget = BudgetService(token_limit=500, cost_limit=1.0)
    budget.reserve(estimated_tokens=400, estimated_cost=0.1)

    with pytest.raises(BudgetExhaustedError, match="Token limit"):
        budget.reserve(estimated_tokens=200, estimated_cost=0.1)


def test_budget_service_blocks_when_exceeding_call_limit():
    budget = BudgetService(call_limit=2)
    op1 = budget.reserve(estimated_tokens=10, estimated_cost=0.01)
    budget.settle(op1, 10, 0.01)

    op2 = budget.reserve(estimated_tokens=10, estimated_cost=0.01)
    budget.settle(op2, 10, 0.01)

    with pytest.raises(BudgetExhaustedError, match="Call limit"):
        budget.reserve(estimated_tokens=10, estimated_cost=0.01)


def test_stagnation_detector_triggers_on_lack_of_progress():
    detector = StagnationDetector(history_window=2)
    state = sample_state()

    # Round 1
    detector.record_round(state, 1)
    assert not detector.is_stagnant()

    # Round 2 with no changes
    detector.record_round(state, 2)
    assert detector.is_stagnant()


def test_workflow_controller_transitions_and_commits():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-1", ttl=30)

            controller = WorkflowController(store, lease)

            # Transition phase
            updated_state = controller.transition_phase(RunPhase.SNAPSHOT)
            assert updated_state.run.phase == RunPhase.SNAPSHOT
            assert updated_state.run.revision == 2

            # Record issue
            issue = Issue(
                id="ISSUE-TEST-1",
                run_id=state.run.id,
                severity=IssueSeverity.WARNING,
                based_on_revision=0,
                claim="Potential race condition",
                impact="Data corruption under load",
                verification_request="Run concurrency test",
                suggested_resolution="Add mutex lock",
                requirement_ids=["REQ-001"],
            )
            updated_state = controller.record_issue(issue)
            assert len(updated_state.issues) == 1
            assert updated_state.issues[0].id == "ISSUE-TEST-1"


def test_f004_budget_counters_match_recalculated_totals():
    """F-004: In-memory counters _reserved_tokens and _reserved_cost must always match sums computed from scratch."""
    budget = BudgetService(token_limit=10000, cost_limit=10.0, call_limit=20)

    # Initially zero
    assert budget.total_reserved_tokens == 0
    assert budget.total_reserved_cost == 0.0

    # Make multiple reservations
    op1 = budget.reserve(estimated_tokens=500, estimated_cost=0.05)
    op2 = budget.reserve(estimated_tokens=300, estimated_cost=0.03)
    op3 = budget.reserve(estimated_tokens=700, estimated_cost=0.07)

    recomputed_tokens = sum(r.tokens for r in budget._reservations.values() if r.status == "reserved")
    recomputed_cost = sum(r.cost for r in budget._reservations.values() if r.status == "reserved")
    assert budget.total_reserved_tokens == recomputed_tokens == 1500
    assert budget.total_reserved_cost == pytest.approx(recomputed_cost) == pytest.approx(0.15)

    # Settle op1
    budget.settle(op1, actual_tokens=450, actual_cost=0.045)
    recomputed_tokens = sum(r.tokens for r in budget._reservations.values() if r.status == "reserved")
    recomputed_cost = sum(r.cost for r in budget._reservations.values() if r.status == "reserved")
    assert budget.total_reserved_tokens == recomputed_tokens == 1000
    assert budget.total_reserved_cost == pytest.approx(recomputed_cost) == pytest.approx(0.10)

    # Release op2
    budget.release(op2)
    recomputed_tokens = sum(r.tokens for r in budget._reservations.values() if r.status == "reserved")
    recomputed_cost = sum(r.cost for r in budget._reservations.values() if r.status == "reserved")
    assert budget.total_reserved_tokens == recomputed_tokens == 700
    assert budget.total_reserved_cost == pytest.approx(recomputed_cost) == pytest.approx(0.07)

    # Cancel all pending
    budget.cancel_all_pending()
    recomputed_tokens = sum(r.tokens for r in budget._reservations.values() if r.status == "reserved")
    recomputed_cost = sum(r.cost for r in budget._reservations.values() if r.status == "reserved")
    assert budget.total_reserved_tokens == recomputed_tokens == 0
    assert budget.total_reserved_cost == pytest.approx(recomputed_cost) == 0.0


def test_f004_budget_service_persists_settle_and_release_across_restart():
    """F-004: settle and release must persist via repository.commit so cost/token survive service restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "budget_persist.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-budget", ttl=60)

            budget1 = BudgetService(
                token_limit=10000,
                cost_limit=5.0,
                repository=store,
                lease=lease,
            )

            op1 = budget1.reserve(estimated_tokens=1000, estimated_cost=0.01)
            budget1.settle(op1, actual_tokens=850, actual_cost=0.0085)

            op2 = budget1.reserve(estimated_tokens=500, estimated_cost=0.005)
            budget1.release(op2)

            op3 = budget1.reserve(estimated_tokens=250, estimated_cost=0.0025)

            # Recreate service from same DB to simulate restart
            budget2 = BudgetService(
                token_limit=10000,
                cost_limit=5.0,
                repository=store,
                lease=lease,
            )

            summary = budget2.get_summary()
            assert summary["used_tokens"] == 850
            assert summary["used_cost"] == pytest.approx(0.0085)
            assert summary["settled_calls"] == 1
            assert budget2.total_reserved_tokens == 250
            assert budget2.total_reserved_cost == pytest.approx(0.0025)


def test_f004_budget_concurrent_threads_reserve_success():
    """F-004: 10 threads reserving concurrently must all succeed via backoff retry, without exceeding budget."""
    import concurrent.futures

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "budget_concurrent.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-concurrent", ttl=120)

            budget = BudgetService(
                token_limit=20000,
                cost_limit=2.0,
                call_limit=20,
                repository=store,
                lease=lease,
            )

            def do_reserve(idx: int) -> str:
                return budget.reserve(
                    estimated_tokens=1000,
                    estimated_cost=0.01,
                    operation_id=f"RES-CONC-{idx}",
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(do_reserve, i) for i in range(10)]
                results = [f.result() for f in futures]

            assert len(results) == 10
            assert len(set(results)) == 10
            assert budget.total_reserved_tokens == 10000
            assert budget.total_reserved_cost == pytest.approx(0.10)
            assert budget.total_reserved_tokens <= 20000
            assert budget.total_reserved_cost <= 2.0


def test_f004_graph_budget_integration_settles_and_releases_without_leak():
    """F-004: Model success settles reservation; model error releases reservation without leak."""
    from astra_multi.persistence.artifacts import FileArtifactStore
    from astra_multi.context.bundle import ContextBuilder
    from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
    from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph

    from astra_multi.agents.roles import (
        AnalysisOutput,
        ProposalOutput,
        ReviewOutput,
        SynthesizerOutput,
        StepDraft,
    )

    should_fail = {"fail": False}

    def controlled_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if should_fail["fail"]:
            raise RuntimeError("Simulated LLM network/provider failure")
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["Ok"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(approach="Ok", alternatives=[], tradeoffs=[], requirement_coverage={"REQ-001": "Ok"}, claim_ids=[])
        elif output_schema == ReviewOutput:
            content = ReviewOutput(summary="Ok", reviewed_evidence_ids=[], issues=[])
        elif output_schema == SynthesizerOutput:
            content = SynthesizerOutput(
                steps=[StepDraft(objective="Step 1", requirement_ids=["REQ-001"], dependencies=[], targets=["main.py"], validation="pytest", deliverables=["main.py"], completion_criteria=["pass"], evidence_ids=[])],
                decisions=[], risks=[], issues_addressed=[], rationale="Ok"
            )
        else:
            content = "ok"
        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"fake-{role}",
            provider="fake",
            usage={"total_tokens": 120},
            cost_actual_usd=0.0012,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "graph_budget.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-graph-budget", ttl=60)

            budget = BudgetService(
                token_limit=10000,
                cost_limit=1.0,
                repository=store,
                lease=lease,
            )
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=controlled_adapter,
            )
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
                budget_service=budget,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # 1. Run with model success: budget must settle
            initial_state = {
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 1,
                "events": [],
            }
            # Execute just up to planner_analysis or run node
            # Test executing planner_analysis_node directly or invoking
            from astra_multi.agents.roles import AnalysisOutput
            res = app.invoke(initial_state)
            # After run, verify budget settled and no reservations leaked
            assert budget.total_reserved_tokens == 0
            assert budget.total_reserved_cost == 0.0
            assert budget.get_summary()["used_tokens"] > 0
            assert budget.get_summary()["settled_calls"] > 0

            # 2. Trigger model failure on a new run: verify release is called and total_reserved drops to 0
            should_fail["fail"] = True
            state2 = sample_state(repo=False)
            run2 = state2.run.model_copy(update={"id": "RUN-002"})
            store.create(state2.task, run2, state2.snapshot)
            lease2 = store.acquire("RUN-002", owner="worker-graph-budget-2", ttl=60)
            controller2 = WorkflowController(store, lease2)
            budget2 = BudgetService(
                token_limit=10000,
                cost_limit=1.0,
                repository=store,
                lease=lease2,
            )
            wf_ctx2 = WorkflowContext(
                controller=controller2,
                gateway=gateway,
                context_builder=context_builder,
                budget_service=budget2,
            )
            app2 = create_workflow_graph(wf_ctx2).compile()

            with pytest.raises(RuntimeError, match="Simulated LLM network/provider failure"):
                app2.invoke({
                    "run_id": "RUN-002",
                    "round": 0,
                    "max_rounds": 1,
                    "events": [],
                })

            # Assert no reservations leaked!
            assert budget2.total_reserved_tokens == 0
            assert budget2.total_reserved_cost == 0.0


def test_record_model_call_accepts_none_estimated_cost():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_none_cost.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-none-cost", ttl=30)
            controller = WorkflowController(store, lease)

            updated_state = controller.record_model_call(
                call_id="CALL-NONE-ESTIMATED-COST",
                role="planner",
                provider="fake",
                model_id="test-model",
                prompt_version="v1",
                input_data="test input",
                usage={"total_tokens": 150},
                estimated_cost=None,
            )
            assert len(updated_state.model_calls) == 1
            assert updated_state.model_calls[0].estimated_cost == 0.0


def test_budget_settle_accepts_none_actual_cost():
    budget = BudgetService(token_limit=1000, cost_limit=1.0)
    op1 = budget.reserve(estimated_tokens=200, estimated_cost=0.02)
    budget.settle(op1, actual_tokens=150, actual_cost=None)
    assert budget.total_reserved_tokens == 0
    assert budget.total_reserved_cost == 0.0
    summary = budget.get_summary()
    assert summary["used_tokens"] == 150
    assert summary["used_cost"] == 0.0
    assert summary["settled_calls"] == 1


def test_graph_execution_handles_none_cost_actual_usd():
    """Verify that graph nodes succeed without ValidationError when model returns cost_actual_usd=None."""
    from astra_multi.agents.roles import (
        AnalysisOutput,
        ProposalOutput,
        ReviewOutput,
        SynthesizerOutput,
        StepDraft,
    )
    from astra_multi.persistence.artifacts import FileArtifactStore
    from astra_multi.context.bundle import ContextBuilder
    from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway, ModelResult
    from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph

    def none_cost_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        if output_schema == AnalysisOutput:
            content = AnalysisOutput(role=role, findings=["Ok"], risks=[], assumptions=[])
        elif output_schema == ProposalOutput:
            content = ProposalOutput(approach="Ok", alternatives=[], tradeoffs=[], requirement_coverage={"REQ-001": "Ok"}, claim_ids=[])
        elif output_schema == ReviewOutput:
            content = ReviewOutput(summary="Ok", reviewed_evidence_ids=[], issues=[])
        elif output_schema == SynthesizerOutput:
            content = SynthesizerOutput(
                steps=[StepDraft(objective="Step 1", requirement_ids=["REQ-001"], dependencies=[], targets=["main.py"], validation="pytest", deliverables=["main.py"], completion_criteria=["pass"], evidence_ids=[])],
                decisions=[], risks=[], issues_addressed=[], rationale="Ok"
            )
        else:
            content = "ok"
        return ModelResult(
            content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
            model_id=f"real-{role}",
            provider="openai",
            usage={"total_tokens": 200},
            cost_actual_usd=None,  # Simulates real LLM provider returning None
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "graph_none_cost.db"
        art_path = Path(tmpdir) / "artifacts"
        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-none-cost", ttl=60)

            budget = BudgetService(
                token_limit=10000,
                cost_limit=1.0,
                repository=store,
                lease=lease,
            )
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=none_cost_adapter,
            )
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
                budget_service=budget,
            )
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            res = app.invoke({
                "run_id": state.run.id,
                "round": 0,
                "max_rounds": 1,
                "events": [],
            })

            final_state = controller.get_state()
            assert len(final_state.model_calls) > 0
            for call in final_state.model_calls:
                assert call.estimated_cost is not None
                assert isinstance(call.estimated_cost, float)
                assert call.estimated_cost >= 0.0
            assert budget.total_reserved_tokens == 0
            assert budget.total_reserved_cost == 0.0

