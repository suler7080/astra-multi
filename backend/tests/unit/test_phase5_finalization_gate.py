"""Unit tests for Phase 5: 5-Pillar Finalization Gate (Structural, Contract, Rubric, Grounding, Issues)."""


from astra_multi.domain.models import (
    ArtifactType,
    AssignmentMatrix,
    Issue,
    IssueSeverity,
    IssueStatus,
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    RequirementType,
    Run,
    RunPhase,
    RunState,
    RunStatus,
    TaskSpec,
    WorkerAssignment,
)
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)

_EVIDENCE_STEP_BY_REQ = {
    "REQ-TECH-001": "STEP-002",
    "REQ-DELIV-001": "STEP-001",
    "REQ-ORG-001": "STEP-002",
}


def _rubric_audit(
    rubric_id: str, req_id: str, status: str = "MET", notes: str = ""
) -> dict[str, object]:
    evidence: list[dict[str, str]] = []
    if status == "MET":
        evidence.append(
            {
                "req_id": req_id,
                "step_id": _EVIDENCE_STEP_BY_REQ.get(req_id, "STEP-002"),
                "checked_field": (
                    "plan.steps[].requirement_fulfillments.concrete_deliverable"
                ),
                "expected": "Concrete deliverable satisfies acceptance criteria",
                "actual": "Deterministic rubric checker matched the deliverable",
                "validator_rule": "RULE-RUBRIC-PASS",
            }
        )
    return {
        "rubric_id": rubric_id,
        "req_id": req_id,
        "status": status,
        "notes": notes,
        "evidence": evidence,
    }


def _build_compliant_state(run_id: str = "run-test-p5") -> RunState:
    task = TaskSpec(
        id=f"task-{run_id}",
        revision=1,
        goal="Build static web portal with file:// support, mockAPI, and layout reuse for 4 devs",
        requirements=[
            Requirement(
                id="REQ-TECH-001",
                text="Chạy trực tiếp qua giao thức file:// không dùng bundler",
                acceptance="Chạy qua file:// không lỗi",
                req_type=RequirementType.TECH,
                verifiable_deliverable="Nhúng script defer load layout.js, không dùng ES module",
                acceptance_criteria=["Không có import/export ES module", "Không gọi fetch file://"],
                expected_artifact_type=ArtifactType.CODE_SNIPPET,
            ),
            Requirement(
                id="REQ-DELIV-001",
                text="Cấu trúc thư mục dự án và giải pháp layout Header/Footer",
                acceptance="Có cấu trúc thư mục rõ ràng",
                req_type=RequirementType.DELIV,
                verifiable_deliverable="Sơ đồ cây thư mục và file layout.js",
                acceptance_criteria=["Có cây thư mục src/, js/, css/", "Có layout.js chèn header"],
                expected_artifact_type=ArtifactType.DIRECTORY_TREE,
            ),
            Requirement(
                id="REQ-ORG-001",
                text="Bảng phân công nhiệm vụ cho đúng 4 lập trình viên",
                acceptance="Chia việc cho 4 dev",
                req_type=RequirementType.ORG,
                verifiable_deliverable="Bảng ma trận chia việc theo file và vai trò",
                acceptance_criteria=["4 vai trò độc lập", "Không chồng chéo file phụ trách"],
                expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
            ),
        ],
    )

    step1 = PlanStep(
        id="STEP-001",
        objective="Thiết lập cấu trúc thư mục và khung layout dự án",
        worker_role="ui",
        owned_files=["src/index.html", "src/js/layout.js", "src/css/style.css"],
        requirement_ids=["REQ-DELIV-001"],
        dependencies=[],
        deliverables=["Cây thư mục src/ và layout.js"],
        completion_criteria=["Thư mục tạo xong và layout.js load thành công"],
        phase_type="setup",
        validation="Kiểm tra tồn tại file",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-DELIV-001",
                fulfilled_by_section="Cấu trúc thư mục dự án",
                concrete_deliverable="""Cấu trúc thư mục hoàn chỉnh:
├── src/
│   ├── index.html
│   ├── js/
│   │   └── layout.js
│   └── css/
│       └── style.css
└── README.md
Đảm bảo các file liên kết trực tiếp không cần web server.""",
                verification_method="Kiểm tra sự tồn tại của file layout.js và index.html",
            )
        ],
    )

    step2 = PlanStep(
        id="STEP-002",
        objective="Phát triển cơ chế nạp layout và phân công 4 lập trình viên",
        worker_role="ui",
        owned_files=["src/js/layout.js"],
        requirement_ids=["REQ-TECH-001", "REQ-ORG-001"],
        dependencies=["STEP-001"],
        deliverables=["layout.js và ma trận phân công 4 dev"],
        completion_criteria=["Layout chèn DOM thành công và đủ 4 thành viên"],
        phase_type="core_module",
        validation="Mở file://index.html kiểm tra header",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-TECH-001",
                fulfilled_by_section="Giải pháp nạp layout cho file://",
                concrete_deliverable="""Đoạn mã mẫu nạp layout không dùng ES Module:
```javascript
// layout.js - Injected directly into DOM
function renderLayout() {
    const header = document.createElement("header");
    header.innerHTML = "<h1>Portal Header</h1>";
    document.body.prepend(header);
}
document.addEventListener("DOMContentLoaded", renderLayout);
```""",
                verification_method="Mở trực tiếp file://index.html kiểm tra header hiển thị",
            ),
            RequirementFulfillment(
                req_id="REQ-ORG-001",
                fulfilled_by_section="Ma trận phân công 4 thành viên",
                concrete_deliverable="""Bảng phân công nhiệm vụ cho 4 thành viên:
| Thành viên | Vai trò | Trách nhiệm & File phụ trách |
|---|---|---|
| Developer 1 | UI & Layout | Xây dựng index.html, layout.js |
| Developer 2 | API & State | MockAPI client, auth logic js/api.js |
| Developer 3 | Business Logic | Chat UI, real-time message handler |
| Developer 4 | QA & Integration | Test runner, tài liệu hướng dẫn |""",
                verification_method="Kiểm tra đối chiếu 4 vai trò độc lập không chồng chéo file",
            ),
        ],
    )

    step3 = PlanStep(
        id="STEP-003",
        objective="Xây dựng mock API client",
        worker_role="api",
        owned_files=["src/js/api.js"],
        requirement_ids=["REQ-TECH-001"],
        dependencies=["STEP-001"],
        deliverables=["src/js/api.js với mock API client"],
        completion_criteria=["API client gọi được mock endpoint"],
        phase_type="core_module",
        validation="Kiểm tra api.js tải và gọi mock endpoint",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-TECH-001",
                fulfilled_by_section="Mock API client",
                concrete_deliverable=(
                    "```javascript\nasync function fetchMessages() {\n"
                    "  return fetch('mock://messages');\n}\n```"
                ),
                verification_method="Gọi fetchMessages trong console",
            )
        ],
    )

    step4 = PlanStep(
        id="STEP-004",
        objective="Xây dựng chat logic",
        worker_role="logic",
        owned_files=["src/js/chat.js"],
        requirement_ids=["REQ-TECH-001"],
        dependencies=["STEP-002"],
        deliverables=["src/js/chat.js với xử lý tin nhắn"],
        completion_criteria=["Chat gửi/nhận tin nhắn qua mock API"],
        phase_type="core_module",
        validation="Kiểm tra chat.js gửi tin nhắn",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-TECH-001",
                fulfilled_by_section="Chat message handler",
                concrete_deliverable=(
                    "```javascript\nfunction sendMessage(text) {\n"
                    "  return api.post('/messages', { text });\n}\n```"
                ),
                verification_method="Gửi tin nhắn thử trong console",
            )
        ],
    )

    step5 = PlanStep(
        id="STEP-005",
        objective="Kiểm thử và tích hợp toàn bộ portal",
        worker_role="qa",
        owned_files=["tests/qa.md"],
        requirement_ids=["REQ-DELIV-001"],
        dependencies=["STEP-003", "STEP-004"],
        deliverables=["tests/qa.md với checklist kiểm thử"],
        completion_criteria=["Checklist QA hoàn chỉnh"],
        phase_type="verification",
        validation="Chạy checklist QA thủ công",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-DELIV-001",
                fulfilled_by_section="QA directory tree",
                concrete_deliverable=(
                    "Cây kiểm thử:\ntests/\n├── qa.md\n└── fixtures/\n"
                    "src/\n├── index.html\n└── js/"
                ),
                verification_method="Kiểm tra sự tồn tại của tests/qa.md",
            )
        ],
    )

    assignment_matrix = AssignmentMatrix(
        workers=[
            WorkerAssignment(
                worker_role="ui",
                display_name="UI & Layout",
                responsibilities=["Dựng index.html và layout tái sử dụng"],
                owned_files=[
                    "src/index.html",
                    "src/js/layout.js",
                    "src/css/style.css",
                ],
                requirement_ids=[
                    "REQ-DELIV-001",
                    "REQ-TECH-001",
                    "REQ-ORG-001",
                ],
                step_ids=["STEP-001", "STEP-002"],
            ),
            WorkerAssignment(
                worker_role="api",
                display_name="API & State",
                responsibilities=["Xây dựng mock API client"],
                owned_files=["src/js/api.js"],
                requirement_ids=["REQ-TECH-001"],
                step_ids=["STEP-003"],
            ),
            WorkerAssignment(
                worker_role="logic",
                display_name="Business Logic",
                responsibilities=["Xử lý chat và trạng thái tin nhắn"],
                owned_files=["src/js/chat.js"],
                requirement_ids=["REQ-TECH-001"],
                step_ids=["STEP-004"],
            ),
            WorkerAssignment(
                worker_role="qa",
                display_name="QA & Integration",
                responsibilities=["Kiểm thử tích hợp và tài liệu QA"],
                owned_files=["tests/qa.md"],
                requirement_ids=["REQ-DELIV-001"],
                step_ids=["STEP-005"],
            ),
        ],
        shared_files=[],
        expected_worker_count=4,
    )

    plan = PlanRevision(
        id=f"plan-{run_id}-rev1",
        run_id=run_id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step1, step2, step3, step4, step5],
        assignment_matrix=assignment_matrix,
    )

    run = Run(
        id=run_id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="greenfield",
        config_hash="0" * 64,
        phase=RunPhase.SEMANTIC_REVIEW,
        status=RunStatus.RUNNING,
    )

    return RunState(
        run=run,
        tasks=[task],
        snapshot=None,
        plans=[plan],
        issues=[],
        evidence=[],
        validations=[],
    )


def test_8_pillar_all_pass():
    """All 8 pillars pass -> can_finalize is True and RunStatus is FINAL."""
    state = _build_compliant_state()
    service = FinalizationService()

    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="Plan satisfies all technical and organizational rubrics.",
        concerns=[],
        rubric_audits=[
            _rubric_audit("RUBRIC-TECH-001", "REQ-TECH-001", notes="No ES Module found"),
            _rubric_audit("RUBRIC-DELIV-001", "REQ-DELIV-001", notes="Tree exists"),
            _rubric_audit("RUBRIC-ORG-001", "REQ-ORG-001", notes="4 devs assigned"),
        ],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is True
    assert decision.target_status == RunStatus.FINAL
    assert len(decision.pillar_results) == 8
    assert all(p.passed for p in decision.pillar_results.values())
    assert decision.pillar_results["structural"].passed is True
    assert decision.pillar_results["contract_deliverable"].passed is True
    assert decision.pillar_results["ownership_contract"].passed is True
    assert decision.pillar_results["rubric_audit"].passed is True
    assert decision.pillar_results["grounding_anti_pattern"].passed is True
    assert decision.pillar_results["issue_resolution"].passed is True
    assert decision.pillar_results["runtime_scope"].passed is True
    assert decision.pillar_results["human_review"].passed is True


def test_5_pillar_structural_gate_failure():
    """Pillar 1: An isolated or disconnected step in a multi-step plan fails the Structural Gate."""
    state = _build_compliant_state()
    # Add an isolated step with no dependencies and no other steps depending on it
    isolated_step = PlanStep(
        id="STEP-999",
        objective="Isolated step without any connection",
        requirement_ids=["REQ-TECH-001"],
        dependencies=[],
        deliverables=["Isolated file"],
        completion_criteria=["Done"],
        validation="None",
    )
    plan = state.plan
    plan.steps.append(isolated_step)

    service = FinalizationService()
    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="All good",
        concerns=[],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["structural"].passed is False
    assert any("Isolated step" in diag or "STEP-999" in diag for diag in decision.pillar_results["structural"].diagnostics)


def test_5_pillar_contract_deliverable_failure():
    """Pillar 2: Deliverable lacking expected artifact format fails Contract & Deliverable Gate."""
    state = _build_compliant_state()
    # Modify Step 2's ASSIGNMENT_TABLE fulfillment to have no table markup or dev assignments
    bad_step2 = PlanStep(
        id="STEP-002",
        objective="Phát triển cơ chế nạp layout và phân công 4 lập trình viên",
        requirement_ids=["REQ-TECH-001", "REQ-ORG-001"],
        dependencies=["STEP-001"],
        deliverables=["layout.js và ma trận phân công 4 dev"],
        completion_criteria=["Layout chèn DOM thành công và đủ 4 thành viên"],
        phase_type="core_module",
        validation="Mở file://index.html kiểm tra header",
        requirement_fulfillments=[
            state.plan.steps[1].requirement_fulfillments[0],
            RequirementFulfillment(
                req_id="REQ-ORG-001",
                fulfilled_by_section="Ma trận phân công",
                concrete_deliverable="Chúng tôi sẽ chia việc sau cho team khi bắt đầu dự án.",
                verification_method="Kiểm tra đối chiếu sau",
            ),
        ],
    )
    new_plan = state.plan.model_copy(update={"steps": [state.plan.steps[0], bad_step2]})
    state = state.model_copy(update={"plans": [new_plan]})

    service = FinalizationService()
    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="Review passed",
        concerns=[],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["contract_deliverable"].passed is False
    assert any("expects artifact type 'assignment_table'" in diag for diag in decision.pillar_results["contract_deliverable"].diagnostics)


def test_rubric_gate_rejects_fabricated_or_unowned_evidence():
    state = _build_compliant_state()
    fabricated = _rubric_audit("RUBRIC-TECH-001", "REQ-TECH-001")
    fabricated["evidence"] = [
        {
            "req_id": "REQ-TECH-001",
            "step_id": "STEP-002",
            "checked_field": "plan.steps[].owned_files",
            "checked_path": "src/outside.py",
            "expected": "File is owned",
            "actual": "Reviewer claims it is owned",
            "validator_rule": "REVIEWER-CLAIM",
        }
    ]
    review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="Review claims all rubrics are MET",
        concerns=[],
        rubric_audits=[
            fabricated,
            _rubric_audit("RUBRIC-DELIV-001", "REQ-DELIV-001"),
            _rubric_audit("RUBRIC-ORG-001", "REQ-ORG-001"),
        ],
    )

    decision = FinalizationService().evaluate(state, review)

    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["rubric_audit"].passed is False
    assert any(
        "without valid deterministic evidence" in diagnostic
        for diagnostic in decision.pillar_results["rubric_audit"].diagnostics
    )


def test_5_pillar_rubric_audit_gate_failure():
    """Pillar 3: A MISSING or PARTIAL status in Reviewer Rubric Audit fails Rubric Audit Gate."""
    state = _build_compliant_state()
    service = FinalizationService()

    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="Review mostly passed",
        concerns=[],
        rubric_audits=[
            _rubric_audit("RUBRIC-TECH-001", "REQ-TECH-001", notes="OK"),
            _rubric_audit(
                "RUBRIC-DELIV-001",
                "REQ-DELIV-001",
                status="PARTIAL",
                notes="Tree missing css/ style.css",
            ),
            _rubric_audit("RUBRIC-ORG-001", "REQ-ORG-001", notes="OK"),
        ],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["rubric_audit"].passed is False
    assert any("RUBRIC-DELIV-001" in diag and "PARTIAL" in diag for diag in decision.pillar_results["rubric_audit"].diagnostics)


def test_5_pillar_grounding_anti_pattern_failure():
    """Pillar 4: Prohibited physical constraint in plan fails Grounding & Anti-Pattern Gate."""
    state = _build_compliant_state()
    # Inject forbidden ES module import into concrete deliverable under file:// constraint
    bad_step2 = PlanStep(
        id="STEP-002",
        objective="Phát triển cơ chế nạp layout và phân công 4 lập trình viên",
        requirement_ids=["REQ-TECH-001", "REQ-ORG-001"],
        dependencies=["STEP-001"],
        deliverables=["layout.js và ma trận phân công 4 dev"],
        completion_criteria=["Layout chèn DOM thành công và đủ 4 thành viên"],
        phase_type="core_module",
        validation="Mở file://index.html kiểm tra header",
        requirement_fulfillments=[
            RequirementFulfillment(
                req_id="REQ-TECH-001",
                fulfilled_by_section="Giải pháp nạp layout",
                concrete_deliverable="""<script type="module">
import { setupHeader } from './header.js';
setupHeader();
</script>""",
                verification_method="Mở trực tiếp file://index.html",
            ),
            state.plan.steps[1].requirement_fulfillments[1],
        ],
    )
    new_plan = state.plan.model_copy(update={"steps": [state.plan.steps[0], bad_step2]})
    state = state.model_copy(update={"plans": [new_plan]})

    service = FinalizationService()
    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="OK",
        concerns=[],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["grounding_anti_pattern"].passed is False
    assert any("file://" in diag or "module" in diag.lower() for diag in decision.pillar_results["grounding_anti_pattern"].diagnostics)


def test_5_pillar_issue_resolution_failure():
    """Pillar 5: Unresolved blocking issue fails Issue Resolution Gate."""
    state = _build_compliant_state()
    state.issues.append(
        Issue(
            id="ISSUE-BLK-001",
            run_id=state.run.id,
            severity=IssueSeverity.BLOCKING,
            status=IssueStatus.OPEN,
            based_on_revision=1,
            claim="Layout injection breaks in Chrome on file:// protocol",
            impact="Header/footer missing",
            suggested_resolution="Use defer layout.js instead",
            verification_request="Verify on chrome with file://",
        )
    )

    service = FinalizationService()
    sem_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=1,
        feedback="OK",
        concerns=[],
    )

    decision = service.evaluate(state, sem_review)

    assert decision.can_finalize is False
    assert decision.target_status == RunStatus.PARTIAL
    assert decision.pillar_results["issue_resolution"].passed is False
    assert any("ISSUE-BLK-001" in diag or "Blocking issue remains unresolved" in diag for diag in decision.pillar_results["issue_resolution"].diagnostics)
