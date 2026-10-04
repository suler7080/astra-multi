"""P4.3 Canonical JSON and Markdown plan exporter.

Generates consistent, verifiable artifacts matching PLAN_TEMPLATE.md:
- Export schema v1.
- Identical content across JSON and Markdown formats.
- Markdown is cleanly escaped without executable HTML injection.
- Preserves requirement coverage, decision log, evidence index, and unresolved issues.
"""

from __future__ import annotations

from typing import Any

from astra_multi.domain.models import RunState


def escape_markdown(text: str) -> str:
    """Safely escapes Markdown characters to prevent layout breakage or HTML execution."""
    replacements = {
        "<": "&lt;",
        ">": "&gt;",
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text


class PlanExporter:
    """Exports a finalized or partial candidate plan into JSON and Markdown artifacts."""

    def export_json(self, state: RunState, custom_status: str | None = None) -> dict[str, Any]:
        task = state.task
        plan = state.plan
        run = state.run

        status_str = custom_status or run.status.value

        payload = {
            "schema_version": 1,
            "metadata": {
                "run_id": run.id,
                "plan_revision": plan.revision if plan else 0,
                "task_revision": task.revision,
                "snapshot_id": run.snapshot_id,
                "status": status_str,
                "stop_reason": run.stop_reason or "",
                "created_at": run.created_at.isoformat(),
            },
            "task": {
                "id": task.id,
                "goal": task.goal,
                "requirements": [
                    {"id": r.id, "text": r.text, "acceptance": r.acceptance}
                    for r in task.requirements
                ],
                "constraints": task.constraints,
                "non_goals": task.non_goals,
            },
            "architecture": {
                "decisions": [
                    {
                        "id": d.id,
                        "question": d.question,
                        "chosen": d.chosen,
                        "rationale": d.rationale,
                        "alternatives": d.alternatives,
                        "evidence_ids": d.evidence_ids,
                    }
                    for d in (plan.decisions if plan else state.decisions)
                ],
            },
            "steps": [
                {
                    "id": s.id,
                    "objective": s.objective,
                    "requirement_ids": s.requirement_ids,
                    "dependencies": s.dependencies,
                    "targets": s.targets,
                    "validation": s.validation,
                    "deliverables": s.deliverables,
                    "completion_criteria": s.completion_criteria,
                    "evidence_ids": s.evidence_ids,
                }
                for s in (plan.steps if plan else [])
            ],
            "issues": [
                {
                    "id": i.id,
                    "severity": i.severity.value,
                    "status": i.status.value,
                    "claim": i.claim,
                    "impact": i.impact,
                    "suggested_resolution": i.suggested_resolution,
                    "resolution": i.resolution.model_dump(mode="json") if i.resolution else None,
                }
                for i in state.issues
            ],
            "evidence": [
                {
                    "id": e.id,
                    "source_type": e.source_type,
                    "locator": e.locator,
                    "content_hash": e.content_hash,
                    "status": e.status.value,
                }
                for e in state.evidence
            ],
        }
        return payload

    def export_markdown(self, state: RunState, custom_status: str | None = None) -> str:
        task = state.task
        plan = state.plan
        run = state.run

        status_str = custom_status or run.status.value

        lines: list[str] = [
            f"# {escape_markdown(task.goal)} — Kế hoạch triển khai",
            "",
            "## 1. Thông tin bản kế hoạch",
            "",
            f"- Run ID: `{run.id}`",
            f"- Plan revision: `{plan.revision if plan else 0}`",
            f"- TaskSpec revision: `{task.revision}`",
            f"- Snapshot ID / manifest hash: `{run.snapshot_id or 'none (greenfield)'}`",
            f"- Trạng thái: **{status_str}**",
            f"- Lý do trạng thái: {escape_markdown(run.stop_reason or 'None')}",
            f"- Ngày tạo: `{run.created_at.isoformat()}`",
            "",
            "## 2. Mục tiêu và phạm vi",
            "",
            "### Mục tiêu",
            "",
            escape_markdown(task.goal),
            "",
            "### Yêu cầu và tiêu chí chấp nhận",
            "",
            "| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |",
            "|---|---|---|",
        ]

        for req in task.requirements:
            lines.append(
                f"| `{req.id}` | {escape_markdown(req.text)} | {escape_markdown(req.acceptance)} |"
            )

        lines.extend([
            "",
            "## 3. Quyết định kiến trúc và trade-off",
            "",
            "| Decision ID | Vấn đề | Lựa chọn | Alternatives | Lý do |",
            "|---|---|---|---|---|",
        ])

        decisions = plan.decisions if plan else state.decisions
        for dec in decisions:
            alts = ", ".join(escape_markdown(a) for a in dec.alternatives) or "none"
            lines.append(
                f"| `{dec.id}` | {escape_markdown(dec.question)} | {escape_markdown(dec.chosen)} | {alts} | {escape_markdown(dec.rationale)} |"
            )

        lines.extend([
            "",
            "## 4. Các bước thực hiện",
            "",
        ])

        if plan:
            for step in plan.steps:
                lines.extend([
                    f"### {step.id} — {escape_markdown(step.objective)}",
                    "",
                    f"- **Mục tiêu:** {escape_markdown(step.objective)}",
                    f"- **Requirements:** {', '.join(f'`{r}`' for r in step.requirement_ids)}",
                    f"- **Phụ thuộc:** {', '.join(f'`{d}`' for d in step.dependencies) if step.dependencies else 'không có'}",
                    f"- **Đầu ra bàn giao:** {', '.join(escape_markdown(d) for d in step.deliverables)}",
                    f"- **Cách xác minh:** {escape_markdown(step.validation)}",
                    f"- **Tiêu chí hoàn thành:** {', '.join(escape_markdown(c) for c in step.completion_criteria)}",
                    "",
                ])
        else:
            lines.append("*Chưa có bước kế hoạch nào được commit.*")
            lines.append("")

        lines.extend([
            "## 5. Issues, rủi ro và trạng thái",
            "",
            "| ID | Nội dung | Mức độ | Trạng thái | Hướng giải quyết |",
            "|---|---|---|---|---|",
        ])

        for issue in state.issues:
            lines.append(
                f"| `{issue.id}` | {escape_markdown(issue.claim)} | {issue.severity.value} | {issue.status.value} | {escape_markdown(issue.suggested_resolution)} |"
            )

        lines.extend([
            "",
            "## 6. Evidence index",
            "",
            "| Evidence ID | Nguồn / locator | Hash | Trạng thái kiểm chứng |",
            "|---|---|---|---|",
        ])

        for ev in state.evidence:
            lines.append(
                f"| `{ev.id}` | `{ev.locator}` | `{ev.content_hash[:16]}...` | {ev.status.value} |"
            )

        lines.append("")
        return "\n".join(lines)
