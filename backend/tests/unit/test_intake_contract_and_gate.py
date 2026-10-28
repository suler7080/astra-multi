"""Unit tests for Phase 1 Requirement 1:
Triệt tiêu lỗi hợp đồng đầu vào tại phase INTAKE và Intake Gate.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    ArtifactType,
    Requirement,
    RequirementType,
    TaskSpec,
)
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.contract_extractor import (
    classify_all,
    classify_requirement,
    detect_deliverable_gaps,
)
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


def test_contract_extractor_3_types_and_metadata():
    """Verify classification into TECH, DELIV, ORG with artifact types and criteria."""
    # 1. TECH constraint
    tech = classify_requirement("Không dùng bất kỳ framework SPA nào, chỉ dùng Bootstrap 5")
    assert tech.req_type == RequirementType.TECH
    assert tech.verifiable_deliverable is None
    assert any("technical constraint" in c for c in tech.acceptance_criteria)

    # 2. DELIV deliverable (directory tree)
    deliv_tree = classify_requirement("Sơ đồ cây thư mục chi tiết (directory tree)")
    assert deliv_tree.req_type == RequirementType.DELIV
    assert deliv_tree.expected_artifact_type == ArtifactType.DIRECTORY_TREE
    assert deliv_tree.verifiable_deliverable == "directory_tree"
    assert any("directory/file tree" in c for c in deliv_tree.acceptance_criteria)

    # 3. DELIV deliverable (layout reuse)
    deliv_layout = classify_requirement("Giải pháp tái sử dụng layout Header/Footer")
    assert deliv_layout.req_type == RequirementType.DELIV
    assert deliv_layout.expected_artifact_type == ArtifactType.CODE_SNIPPET
    assert deliv_layout.verifiable_deliverable == "code_snippet"

    # 4. ORG requirement (assignment table for 4 devs)
    org = classify_requirement("Bảng ma trận phân công công việc cho đúng 4 lập trình viên")
    assert org.req_type == RequirementType.ORG
    assert org.expected_artifact_type == ArtifactType.ASSIGNMENT_TABLE
    assert org.verifiable_deliverable == "assignment_table"
    assert any("team member to specific files" in c for c in org.acceptance_criteria)


def test_classify_all_typed_ids_generation():
    """Verify classify_all produces contiguous typed IDs."""
    raw_reqs = [
        "Mở trực tiếp qua file:// không dùng bundler",
        "Sơ đồ cây thư mục dự án",
        "Bảng phân công 4 thành viên không xung đột",
    ]
    expected_outputs = [
        "Giải pháp tái sử dụng layout Header/Footer",
    ]
    items = classify_all(raw_reqs, expected_outputs)
    ids = [item[0] for item in items]
    types = [item[1].req_type for item in items]

    assert ids == [
        "REQ-TECH-001",
        "REQ-DELIV-001",
        "REQ-ORG-001",
        "REQ-DELIV-002",
    ]
    assert types == [
        RequirementType.TECH,
        RequirementType.DELIV,
        RequirementType.ORG,
        RequirementType.DELIV,
    ]


def test_detect_deliverable_gaps_finds_uncovered_nouns():
    """Verify detect_deliverable_gaps identifies deliverables mentioned in goal but missing in requirements."""
    task = TaskSpec(
        id="TASK-001",
        goal="Thiết kế kiến trúc trang tin tức, yêu cầu có sơ đồ thư mục chi tiết, giải pháp tái sử dụng layout Header/Footer và bảng phân công 4 lập trình viên.",
        requirements=[
            Requirement(
                id="REQ-TECH-001",
                text="Chỉ dùng HTML/CSS/JS thuần, không dùng framework",
                acceptance="pass",
                req_type=RequirementType.TECH,
            )
        ],
    )
    gaps = detect_deliverable_gaps(task)
    gap_titles = [g.text for g in gaps]

    # Should detect directory_tree, layout_reuse, and assignment_table
    assert any("thư mục" in t.lower() for t in gap_titles)
    assert any("layout" in t.lower() for t in gap_titles)
    assert any("phân công" in t.lower() for t in gap_titles)


def test_intake_gate_reruns_and_synthesizes_missing_contracts_in_graph():
    """Integration test: graph's intake_gate catches gaps, reruns intake, revises task, then passes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)
            state = sample_state(repo=False)

            # Define goal requiring deliverables that are NOT in requirements
            task_with_gaps = TaskSpec(
                id=state.task.id,
                goal="Thiết kế web tuyển dụng: cần sơ đồ cây thư mục và bảng phân công 4 thành viên.",
                requirements=[
                    Requirement(
                        id="REQ-TECH-001",
                        text="Không dùng backend Node/Python",
                        acceptance="pass",
                        req_type=RequirementType.TECH,
                    )
                ],
            )
            store.create(task_with_gaps, state.run, state.snapshot)

            from astra_multi.agents.roles import (
                AnalysisOutput,
                AssignmentMatrixDraft,
                ProposalOutput,
                ReviewOutput,
                StepDraft,
                SynthesizerOutput,
                WorkerAssignmentDraft,
            )
            from astra_multi.gateway.model_gateway import ModelResult

            def mock_adapter(provider, role, messages, output_schema=None, **kwargs):
                if output_schema == AnalysisOutput:
                    content = AnalysisOutput(role=role, findings=["ok"], risks=[], assumptions=[])
                elif output_schema == ProposalOutput:
                    content = ProposalOutput(approach="ok", alternatives=[], tradeoffs=[], requirement_coverage={}, claim_ids=[])
                elif output_schema == ReviewOutput:
                    content = ReviewOutput(summary="ok", issues=[], resolutions=[])
                elif output_schema == SynthesizerOutput:
                    curr_task = store.load(state.run.id).task
                    all_ids = [r.id for r in curr_task.requirements]
                    content = SynthesizerOutput(
                        steps=[
                            StepDraft(
                                objective="step",
                                worker_role="dev1",
                                owned_files=["src/main.js"],
                                requirement_ids=all_ids,
                                targets=[],
                                validation="ok",
                                deliverables=["a"],
                                completion_criteria=["b"],
                            )
                        ],
                        assignment_matrix=AssignmentMatrixDraft(
                            workers=[
                                WorkerAssignmentDraft(
                                    worker_role="dev1",
                                    display_name="Developer 1",
                                    responsibilities=["Implement the plan"],
                                    owned_files=["src/main.js"],
                                    requirement_ids=all_ids,
                                    step_ids=["STEP-1"],
                                )
                            ],
                            shared_files=[],
                        ),
                        decisions=[], risks=[], issues_addressed=[], rationale="ok"
                    )
                else:
                    content = "ok"
                return ModelResult(
                    content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
                    model_id="fake", provider="fake"
                )

            lease = store.acquire(state.run.id, owner="P4-quality-service", ttl=300)
            controller = WorkflowController(store, lease, actor="P4-quality-service")
            gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False), provider_adapter=mock_adapter)
            context_builder = ContextBuilder(art_store)
            wf_ctx = WorkflowContext(controller=controller, gateway=gateway, context_builder=context_builder)
            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            # Execute graph up to snapshot / investigate
            # By passing max_rounds=1 and inspecting events
            result = app.invoke(
                {"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []},
                config={"recursion_limit": 50},
            )

            # Check that intake gate rejected initially, then reran intake and passed
            events_str = " ".join(result.get("events", []))
            assert "[INTAKE_GATE] Gate REJECTED" in events_str
            assert "[INTAKE] Synthesized" in events_str
            assert "[INTAKE_GATE] Contract Gate PASSED" in events_str

            # Check that task was revised in store with synthesized requirements
            final_task = store.load(state.run.id).task
            assert final_task.revision > 1
            final_req_ids = [r.id for r in final_task.requirements]
            assert "REQ-TECH-001" in final_req_ids
            assert any(r_id.startswith("REQ-DELIV-") for r_id in final_req_ids)
            assert any(r_id.startswith("REQ-ORG-") for r_id in final_req_ids)
