"""Role group mappings and orchestration role registry for Astra Multi."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Ánh xạ từ node / role sang nhóm cấu hình (planner / reviewer / synthesizer)
ROLE_GROUP: dict[str, str] = {
    # Nodes in graph.py calling LLM
    "planner_analysis": "planner",
    "reviewer_analysis": "reviewer",
    "propose": "planner",
    "review": "reviewer",
    "revise": "synthesizer",
    "semantic_review": "synthesizer",
    # Direct canonical roles lookup
    "planner": "planner",
    "reviewer": "reviewer",
    "synthesizer": "synthesizer",
}

# Tập hợp tất cả các node trong graph.py thực hiện gọi mô hình LLM
LLM_CALLING_NODES: frozenset[str] = frozenset({
    "planner_analysis",
    "reviewer_analysis",
    "propose",
    "review",
    "revise",
    "semantic_review",
})

# Các nhóm vai trò cấu hình hợp lệ
SUPPORTED_ROLE_GROUPS: frozenset[str] = frozenset({
    "planner",
    "reviewer",
    "synthesizer",
})
