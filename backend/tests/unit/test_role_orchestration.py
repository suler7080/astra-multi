"""Unit tests for Multi-model per role in orchestration (Task 2)."""

import logging
from unittest.mock import MagicMock
import pytest

from astra_multi.gateway.model_gateway import ModelGateway
from astra_multi.orchestration.graph import WorkflowContext, create_workflow_graph
from astra_multi.orchestration.roles import ROLE_GROUP
from astra_multi.schemas import ModelResult


def test_get_assignment_for_role_configured():
    """Verify get_assignment_for_role with complete role assignments."""
    role_assignments = {
        "planner": {"provider": "google", "model": "gemini-2.0-flash"},
        "reviewer": {"provider": "openai", "model": "gpt-4o"},
        "synthesizer": {"provider": "xkiro", "model": "qwen/qwen3.7-flash:free"},
    }
    wf_ctx = WorkflowContext(
        controller=MagicMock(),
        gateway=MagicMock(),
        context_builder=MagicMock(),
        provider="active-fallback",
        role_assignments=role_assignments,
    )

    # Planner group
    assert wf_ctx.get_assignment_for_role("planner") == ("google", "gemini-2.0-flash")
    assert wf_ctx.get_assignment_for_role("planner_analysis") == ("google", "gemini-2.0-flash")
    assert wf_ctx.get_assignment_for_role("propose") == ("google", "gemini-2.0-flash")

    # Reviewer group
    assert wf_ctx.get_assignment_for_role("reviewer") == ("openai", "gpt-4o")
    assert wf_ctx.get_assignment_for_role("reviewer_analysis") == ("openai", "gpt-4o")
    assert wf_ctx.get_assignment_for_role("review") == ("openai", "gpt-4o")

    # Synthesizer group
    assert wf_ctx.get_assignment_for_role("synthesizer") == ("xkiro", "qwen/qwen3.7-flash:free")
    assert wf_ctx.get_assignment_for_role("revise") == ("xkiro", "qwen/qwen3.7-flash:free")
    assert wf_ctx.get_assignment_for_role("semantic_review") == ("xkiro", "qwen/qwen3.7-flash:free")


def test_get_assignment_for_role_missing_and_partial():
    """Verify get_assignment_for_role falls back to active provider when missing or partial."""
    # Empty assignments
    wf_ctx_empty = WorkflowContext(
        controller=MagicMock(),
        gateway=MagicMock(),
        context_builder=MagicMock(),
        provider="active-fallback",
        role_assignments={},
    )
    assert wf_ctx_empty.get_assignment_for_role("planner") == ("active-fallback", None)
    assert wf_ctx_empty.get_assignment_for_role("review") == ("active-fallback", None)

    # Partial assignment (only reviewer configured)
    wf_ctx_partial = WorkflowContext(
        controller=MagicMock(),
        gateway=MagicMock(),
        context_builder=MagicMock(),
        provider="active-fallback",
        role_assignments={"reviewer": {"provider": "openai", "model": None}},
    )
    assert wf_ctx_partial.get_assignment_for_role("propose") == ("active-fallback", None)
    assert wf_ctx_partial.get_assignment_for_role("review") == ("openai", None)


def test_get_assignment_for_role_unknown_role(caplog):
    """Verify unknown node role logs a warning and safely falls back without raising exception."""
    wf_ctx = WorkflowContext(
        controller=MagicMock(),
        gateway=MagicMock(),
        context_builder=MagicMock(),
        provider="active-fallback",
        role_assignments={"planner": {"provider": "google", "model": "gemini"}},
    )
    with caplog.at_level(logging.WARNING):
        result = wf_ctx.get_assignment_for_role("non_existent_role_node")
    assert result == ("active-fallback", None)
    assert "Unrecognized node role 'non_existent_role_node'" in caplog.text


def test_node_execution_dispatches_configured_role_provider_and_model():
    """Verify node execution invokes gateway.call with the role's assigned provider and limits_override."""
    mock_gateway = MagicMock()
    mock_gateway.config.default_max_retries = 1
    mock_gateway.config.default_timeout = 60
    mock_gateway.call.return_value = ModelResult(
        content={
            "findings": ["Found architecture pattern"],
            "risks": [],
            "assumptions": [],
            "evidence_ids": [],
            "role": "planner",
        },
        usage={"total_tokens": 42},
        model_id="gemini-2.0-flash-001",
        provider="google",
    )

    mock_ctrl = MagicMock()
    mock_builder = MagicMock()
    mock_builder.tokenizer.count.return_value = 100
    mock_bundle = MagicMock()
    mock_bundle.role = "planner"
    mock_bundle.content = {"task": "test"}
    mock_builder.build_context.return_value = mock_bundle

    role_assignments = {
        "planner": {"provider": "google", "model": "gemini-2.0-flash"},
    }
    wf_ctx = WorkflowContext(
        controller=mock_ctrl,
        gateway=mock_gateway,
        context_builder=mock_builder,
        provider="active-default",
        role_assignments=role_assignments,
    )

    graph = create_workflow_graph(wf_ctx)
    planner_fn = graph.nodes["planner_analysis"].runnable
    result = planner_fn.invoke({"round": 0, "events": []})

    assert len(result["analyses"]) == 1
    mock_gateway.call.assert_called_once()
    _, kwargs = mock_gateway.call.call_args
    assert kwargs["provider"] == "google"
    assert kwargs["limits_override"] == {"model": "gemini-2.0-flash"}

    # Verify telemetry recorded actual model_id
    mock_ctrl.record_model_call.assert_called_once()
    _, rec_kwargs = mock_ctrl.record_model_call.call_args
    assert rec_kwargs["model_id"] == "gemini-2.0-flash-001"
    assert rec_kwargs["provider"] == "google"


def test_node_execution_fallback_on_role_provider_error(caplog):
    """Verify fallback when role provider fails: logs warning and retries once with active provider."""
    mock_gateway = MagicMock()
    mock_gateway.config.default_max_retries = 1
    mock_gateway.config.default_timeout = 60

    calls = []

    def mock_call(provider, role, messages, output_schema=None, limits_override=None, **kwargs):
        calls.append({"provider": provider, "limits_override": limits_override})
        if provider == "broken_prov":
            raise RuntimeError("API key invalid on broken_prov")
        return ModelResult(
            content={
                "findings": ["Fallback review finding"],
                "risks": [],
                "assumptions": [],
                "evidence_ids": [],
                "role": "reviewer",
            },
            usage={"total_tokens": 30},
            model_id="active-default-model-id",
        )

    mock_gateway.call.side_effect = mock_call

    mock_ctrl = MagicMock()
    mock_builder = MagicMock()
    mock_builder.tokenizer.count.return_value = 100
    mock_bundle = MagicMock()
    mock_bundle.role = "reviewer"
    mock_bundle.content = {"task": "test"}
    mock_builder.build_context.return_value = mock_bundle

    role_assignments = {
        "reviewer": {"provider": "broken_prov", "model": "broken-model"},
    }
    wf_ctx = WorkflowContext(
        controller=mock_ctrl,
        gateway=mock_gateway,
        context_builder=mock_builder,
        provider="active-safe-prov",
        role_assignments=role_assignments,
    )

    graph = create_workflow_graph(wf_ctx)
    reviewer_fn = graph.nodes["reviewer_analysis"].runnable

    with caplog.at_level(logging.WARNING):
        result = reviewer_fn.invoke({"round": 0, "events": []})

    assert len(result["analyses"]) == 1
    # Verify calls: first to broken_prov with override, second to active-safe-prov without override
    assert len(calls) == 2
    assert calls[0]["provider"] == "broken_prov"
    assert calls[0]["limits_override"] == {"model": "broken-model"}
    assert calls[1]["provider"] == "active-safe-prov"
    assert calls[1]["limits_override"] is None

    # Verify warning logged clearly
    assert "Call failed for role 'reviewer' using role provider 'broken_prov'" in caplog.text
    assert "Falling back to active provider 'active-safe-prov'" in caplog.text

    # Verify telemetry recorded actual model_id
    mock_ctrl.record_model_call.assert_called_once()
    _, rec_kwargs = mock_ctrl.record_model_call.call_args
    assert rec_kwargs["model_id"] == "active-default-model-id"


def test_node_execution_unconfigured_matches_default():
    """Verify that with no role_assignments configured, provider is active provider and limits_override is None."""
    mock_gateway = MagicMock()
    mock_gateway.config.default_max_retries = 1
    mock_gateway.config.default_timeout = 60
    mock_gateway.call.return_value = ModelResult(
        content={
            "findings": ["Default finding"],
            "risks": [],
            "assumptions": [],
            "evidence_ids": [],
            "role": "planner",
        },
        usage={"total_tokens": 25},
        model_id="default-active-model",
    )

    mock_ctrl = MagicMock()
    mock_builder = MagicMock()
    mock_builder.tokenizer.count.return_value = 100
    mock_bundle = MagicMock()
    mock_bundle.role = "planner"
    mock_bundle.content = {"task": "test"}
    mock_builder.build_context.return_value = mock_bundle

    wf_ctx = WorkflowContext(
        controller=mock_ctrl,
        gateway=mock_gateway,
        context_builder=mock_builder,
        provider="default-active-prov",
        role_assignments={},
    )

    graph = create_workflow_graph(wf_ctx)
    planner_fn = graph.nodes["planner_analysis"].runnable
    result = planner_fn.invoke({"round": 0, "events": []})

    assert len(result["analyses"]) == 1
    mock_gateway.call.assert_called_once()
    _, kwargs = mock_gateway.call.call_args
    assert kwargs["provider"] == "default-active-prov"
    assert kwargs["limits_override"] is None


def test_run_metadata_snapshot_isolation():
    """Verify run metadata snapshot protects execution from changes to settings store."""
    from astra_multi.persistence.settings_store import SettingsStore
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    store = SettingsStore(lambda: conn)

    # 1. User configures initial mapping
    store.save_role_mappings({
        "planner": {"provider": "p1", "model": "m1"},
    })

    # 2. Run is created and snapshots role_mappings
    run_id = "RUN-123"
    snapshot = store.get_role_mappings()
    store.save_run_role_mappings_snapshot(run_id, snapshot)

    # 3. User later modifies settings in store
    store.save_role_mappings({
        "planner": {"provider": "p2_changed", "model": "m2_changed"},
    })

    # 4. Run execution loads snapshot, unaffected by step 3
    run_snapshot = store.get_run_role_mappings_snapshot(run_id)
    assert run_snapshot == {"planner": {"provider": "p1", "model": "m1"}}
    assert run_snapshot != store.get_role_mappings()
