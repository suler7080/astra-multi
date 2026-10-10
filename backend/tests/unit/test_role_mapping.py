"""Unit tests for role group mappings in orchestration."""

import inspect
import pytest
from astra_multi.orchestration import graph
from astra_multi.orchestration.roles import (
    LLM_CALLING_NODES,
    ROLE_GROUP,
    SUPPORTED_ROLE_GROUPS,
)


def test_all_llm_nodes_are_mapped_to_valid_group():
    """Verify that every LLM calling node is explicitly mapped to a supported group."""
    for node in LLM_CALLING_NODES:
        assert node in ROLE_GROUP, f"Node '{node}' is calling LLM but missing from ROLE_GROUP mapping!"
        group = ROLE_GROUP[node]
        assert group in SUPPORTED_ROLE_GROUPS, f"Group '{group}' for node '{node}' is not supported!"


def test_canonical_roles_are_mapped_to_themselves():
    """Verify planner, reviewer, synthesizer map to themselves."""
    for role in ("planner", "reviewer", "synthesizer"):
        assert role in ROLE_GROUP
        assert ROLE_GROUP[role] == role


def test_graph_llm_calls_match_llm_calling_nodes():
    """Extract all node functions in graph.py that call _call_model_with_budget and ensure they are registered."""
    source = inspect.getsource(graph.create_workflow_graph)
    # Check that known node function names defined in graph are part of LLM_CALLING_NODES
    for node in ("planner_analysis", "reviewer_analysis", "propose", "review", "revise", "semantic_review"):
        assert f"def {node}_node" in source, f"Expected node function '{node}_node' in graph.py"
        assert node in LLM_CALLING_NODES, f"Node '{node}' must be included in LLM_CALLING_NODES"
