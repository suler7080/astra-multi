"""Semantic Review Rubric Checker.

Evaluates candidate plans deterministically against requirement acceptance criteria
to prevent superficial coverage ("phủ cho đủ") and ensure substantive implementation proof:
- Reusable Layout Header/Footer code snippet / loading mechanism
- 4-member non-conflicting task assignment matrix
- Directory tree structure
- Prohibited technology compliance
"""

from __future__ import annotations

import re
from typing import Sequence

from astra_multi.agents.roles import RequirementVerdict
from astra_multi.domain.models import (
    ArtifactType,
    DesignArtifact,
    PlanRevision,
    Requirement,
    RequirementType,
    TaskSpec,
)


def evaluate_semantic_rubrics(
    task: TaskSpec,
    plan: PlanRevision | None,
    design_artifacts: Sequence[DesignArtifact] | None = None,
) -> list[RequirementVerdict]:
    """Evaluates each requirement against concrete deliverables in plan steps and design artifacts."""
    verdicts: list[RequirementVerdict] = []
    steps = plan.steps if plan else []
    da_pool = list(design_artifacts or [])
    if plan and getattr(plan, "design_artifacts", None):
        for da in plan.design_artifacts:
            if da not in da_pool:
                da_pool.append(da)

    for req in task.requirements:
        req_id = req.id
        req_text_lower = req.text.lower()
        req_acc_lower = req.acceptance.lower()

        # Gather all fulfillments for this requirement
        step_fulfillments = [
            rf
            for s in steps
            for rf in (getattr(s, "requirement_fulfillments", []) or [])
            if getattr(rf, "req_id", "") == req_id
        ]
        # Also check steps that list req_id in step.requirement_ids as fallback
        step_deliverables = [
            d
            for s in steps
            if req_id in s.requirement_ids
            for d in s.deliverables
        ]
        da_matches = [da for da in da_pool if req_id in da.requirement_ids]

        if not step_fulfillments and not step_deliverables and not da_matches:
            verdicts.append(
                RequirementVerdict(
                    requirement_id=req_id,
                    restated=req.text,
                    mechanism="None",
                    verdict="FAIL",
                    gap=f"Yêu cầu {req_id} hoàn toàn không có bước thực hiện hoặc artifact thiết kế nào đảm nhận.",
                )
            )
            continue

        deliv_parts: list[str] = []
        section_parts: list[str] = []
        for rf in step_fulfillments:
            if rf.concrete_deliverable:
                deliv_parts.append(rf.concrete_deliverable.strip())
            if rf.fulfilled_by_section:
                section_parts.append(rf.fulfilled_by_section.strip())
        for d in step_deliverables:
            deliv_parts.append(d.strip())
        for da in da_matches:
            deliv_parts.append(da.content.strip())
            section_parts.append(da.title.strip())

        combined_deliv = " ".join(deliv_parts).strip()
        combined_sections = " ".join(section_parts).strip()
        combined_all = f"{combined_deliv} {combined_sections}".strip()
        all_lower = combined_all.lower()

        # 1. Superficiality / empty check
        if len(combined_all) < 20:
            verdicts.append(
                RequirementVerdict(
                    requirement_id=req_id,
                    restated=req.text,
                    mechanism=combined_sections or "Vague",
                    verdict="FAIL",
                    gap=f"concrete_deliverable cho {req_id} quá ngắn (< 20 ký tự), thiếu nội dung giải quyết kỹ thuật cụ thể.",
                )
            )
            continue

        # 2. Echo check: merely restates requirement text or acceptance
        if (
            combined_deliv.lower() == req_text_lower
            or combined_deliv.lower() == req_acc_lower
            or combined_deliv.lower() in ("nêu cơ chế", "xác minh sau", "đã phủ requirement", "tbd")
        ):
            verdicts.append(
                RequirementVerdict(
                    requirement_id=req_id,
                    restated=req.text,
                    mechanism="Echo",
                    verdict="FAIL",
                    gap=f"concrete_deliverable chỉ nhắc lại đề bài ({req_id}) mà không có nội dung giải quyết kỹ thuật thực chất.",
                )
            )
            continue

        # 3. Domain Rubric: Team Assignment Matrix (REQ-ORG / 4 members)
        is_org_assignment = (
            req.req_type == RequirementType.ORG
            or req.expected_artifact_type == ArtifactType.ASSIGNMENT_TABLE
            or any(kw in req_text_lower or kw in req_acc_lower for kw in ("phân công", "4 thành viên", "4 người", "matrix", "vai trò"))
        )
        if is_org_assignment:
            # Must mention multiple distinct roles/members or have table format
            has_table = "|" in combined_all and "-|-" in combined_all or "|" in combined_all and combined_all.count("|") >= 6
            role_keywords = [
                "frontend", "ui", "api", "state", "backend", "layout", "router", "qa",
                "integration", "thành viên", "member", "dev 1", "dev 2", "dev 3", "dev 4",
                "người 1", "người 2", "người 3", "người 4",
            ]
            roles_found = {kw for kw in role_keywords if kw in all_lower}
            if not has_table and len(roles_found) < 3:
                verdicts.append(
                    RequirementVerdict(
                        requirement_id=req_id,
                        restated=req.text,
                        mechanism=combined_sections or "Assignment",
                        verdict="FAIL",
                        gap="Thiếu bảng phân công nhiệm vụ cụ thể cho từng thành viên/vai trò và quy tắc phân chia file chống xung đột.",
                    )
                )
                continue

        # 4. Domain Rubric: Reusable Layout Header/Footer
        is_layout = (
            req.expected_artifact_type == ArtifactType.CODE_SNIPPET
            or any(kw in req_text_lower or kw in req_acc_lower for kw in ("layout", "header", "footer", "tái sử dụng"))
        )
        if is_layout:
            layout_mechanisms = [
                "fetch", "partial", "header.html", "footer.html",
                "custom element", "customelement", "loadpartial", "renderlayout",
                "innerhtml", "domparser", "iframe", "function render",
                "render_header", "render_footer", "<template>", "template tag",
                "load_layout", "shared_layout",
            ]
            has_layout_mech = any(kw in all_lower for kw in layout_mechanisms)
            if not has_layout_mech:
                verdicts.append(
                    RequirementVerdict(
                        requirement_id=req_id,
                        restated=req.text,
                        mechanism=combined_sections or "Layout",
                        verdict="FAIL",
                        gap="Thiếu giải pháp kỹ thuật cụ thể (code mẫu fetch/render partial hoặc custom element) để tái sử dụng layout Header/Footer khi không dùng SPA framework.",
                    )
                )
                continue

        # 5. Domain Rubric: Directory Tree
        is_dir_tree = (
            req.expected_artifact_type == ArtifactType.DIRECTORY_TREE
            or any(kw in req_text_lower or kw in req_acc_lower for kw in ("cây thư mục", "sơ đồ thư mục", "cấu trúc thư mục"))
        )
        if is_dir_tree:
            has_tree_paths = "/" in combined_all and any(
                p in all_lower for p in ("src/", "js/", "css/", "assets/", "index.html", "components/", "partials/")
            )
            if not has_tree_paths:
                verdicts.append(
                    RequirementVerdict(
                        requirement_id=req_id,
                        restated=req.text,
                        mechanism=combined_sections or "Directory",
                        verdict="FAIL",
                        gap="Thiếu sơ đồ cây thư mục chi tiết thể hiện phân chia mã nguồn rõ ràng.",
                    )
                )
                continue

        # 6. Domain Rubric: Forbidden tech check
        is_forbidden_tech = (
            req.req_type == RequirementType.TECH
            and any(kw in req_text_lower for kw in ("công nghệ bị cấm", "không dùng framework", "file://"))
        )
        if is_forbidden_tech:
            forbidden_triggers = ["thư mục build", "npm run build", "webpack build", "vite build", "express backend"]
            bad_matches = [trig for trig in forbidden_triggers if trig in all_lower]
            if bad_matches:
                verdicts.append(
                    RequirementVerdict(
                        requirement_id=req_id,
                        restated=req.text,
                        mechanism=combined_sections or "Tech Constraints",
                        verdict="FAIL",
                        gap=f"Kế hoạch mâu thuẫn với ràng buộc công nghệ bị cấm: xuất hiện cụm từ '{bad_matches[0]}'.",
                    )
                )
                continue

        # All checks passed
        verdicts.append(
            RequirementVerdict(
                requirement_id=req_id,
                restated=req.text,
                mechanism=combined_sections or combined_deliv[:100],
                verdict="PASS",
                gap=None,
            )
        )

    return verdicts
