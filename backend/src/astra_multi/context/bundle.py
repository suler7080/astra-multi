from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any, Protocol

from pydantic import Field

from astra_multi.domain.models import (
    Contract,
    Evidence,
    IssueStatus,
    RunPhase,
    RunState,
)
from astra_multi.domain.repositories import ArtifactStore

logger = logging.getLogger(__name__)


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


class ByteTokenizer:
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


# Default budget for orchestration nodes. Previous value 4000 bytes was too
# small: task + plan + open_issues alone could exceed it even for greenfield
# runs with short goals, causing spurious ContextOverflow
# ("task/snapshot/essential source references exceed limit").
# 12000 bytes ~= 3000 tokens, enough for plan + issues while staying safe.
DEFAULT_ORCHESTRATION_MAX_TOKENS = 12000


def resolve_orchestration_limit(default: int = DEFAULT_ORCHESTRATION_MAX_TOKENS) -> int:
    """Resolve orchestration context limit, allowing env override."""
    raw = os.environ.get("ASTRA_MULTI_MAX_CONTEXT_BYTES", "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid ASTRA_MULTI_MAX_CONTEXT_BYTES=%r, using %d", raw, default)
        return default
    if value < 1:
        logger.warning("Invalid ASTRA_MULTI_MAX_CONTEXT_BYTES=%r, using %d", raw, default)
        return default
    return value


def orchestration_limits(
    max_repo_entries: int = 64,
    max_tokens: int | None = None,
) -> ContextLimits:
    """Build ContextLimits used by orchestration graph nodes."""
    return ContextLimits(
        max_tokens=max_tokens or resolve_orchestration_limit(),
        max_repo_entries=max_repo_entries,
    )


class ContextLimits(Contract):
    max_tokens: Annotated[int, Field(ge=1)] = 16000
    max_repo_entries: Annotated[int, Field(ge=0, le=1000)] = 64


class ContextBundle(Contract):
    run_id: str
    snapshot_id: str | None
    role: str
    phase: RunPhase
    content: str
    source_ids: tuple[str, ...]
    truncated_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    token_count: int
    tokenizer: str
    omitted_repo_paths: tuple[str, ...]


class ContextOverflow(ValueError):
    pass


def _truncate_text(value: Any, max_text: int) -> Any:
    if isinstance(value, str) and len(value) > max_text:
        return value[:max_text] + f"…[truncated {len(value) - max_text} chars]"
    return value


def _summarize_issue(issue: dict[str, Any], max_text: int = 200) -> dict[str, Any]:
    """Keep all keys but truncate long free-text fields."""
    out = dict(issue)
    for key in ("claim", "impact", "verification_request", "suggested_resolution"):
        if key in out:
            out[key] = _truncate_text(out[key], max_text)
    # Drop verbose history/resolution details, keep status info.
    if isinstance(out.get("history"), list):
        out["history"] = [
            {"status": h.get("status"), "actor": h.get("actor"), "reason": _truncate_text(h.get("reason"), 100)}
            for h in out["history"][-3:]
            if isinstance(h, dict)
        ]
    if isinstance(out.get("resolution"), dict):
        res = dict(out["resolution"])
        if "text" in res:
            res["text"] = _truncate_text(res["text"], max_text)
        out["resolution"] = res
    return out


def _minimal_issue(issue: dict[str, Any], max_text: int = 100) -> dict[str, Any]:
    return {
        "id": issue.get("id"),
        "severity": issue.get("severity"),
        "status": issue.get("status"),
        "claim": _truncate_text(issue.get("claim", ""), max_text),
        "requirement_ids": issue.get("requirement_ids", []),
    }


def _summarize_plan(plan: dict[str, Any], max_text: int = 200) -> dict[str, Any]:
    out = dict(plan)
    steps = []
    for s in plan.get("steps", []):
        if not isinstance(s, dict):
            continue
        ns = dict(s)
        ns["objective"] = _truncate_text(ns.get("objective", ""), max_text)
        ns["validation"] = _truncate_text(ns.get("validation", ""), max_text)
        # Keep DAG-critical fields intact; trim verbose lists.
        if isinstance(ns.get("deliverables"), list):
            ns["deliverables"] = [_truncate_text(v, max_text) for v in ns["deliverables"][:2]]
        if isinstance(ns.get("completion_criteria"), list):
            ns["completion_criteria"] = [_truncate_text(v, max_text) for v in ns["completion_criteria"][:2]]
        if isinstance(ns.get("targets"), list):
            ns["targets"] = ns["targets"][:5]
        steps.append(ns)
    out["steps"] = steps
    decs = []
    for d in plan.get("decisions", []):
        if not isinstance(d, dict):
            continue
        nd = dict(d)
        nd["rationale"] = _truncate_text(nd.get("rationale", ""), max_text)
        nd["chosen"] = _truncate_text(nd.get("chosen", ""), max_text)
        if isinstance(nd.get("alternatives"), list):
            nd["alternatives"] = [_truncate_text(v, max_text) for v in nd["alternatives"][:3]]
        decs.append(nd)
    out["decisions"] = decs
    if isinstance(out.get("risks"), list):
        out["risks"] = [_truncate_text(v, max_text) for v in out["risks"][:5]]
    return out


def _minimal_plan(plan: dict[str, Any], max_text: int = 100) -> dict[str, Any]:
    steps = []
    for s in plan.get("steps", []):
        if not isinstance(s, dict):
            continue
        steps.append(
            {
                "id": s.get("id"),
                "objective": _truncate_text(s.get("objective", ""), max_text),
                "requirement_ids": s.get("requirement_ids", []),
                "dependencies": s.get("dependencies", []),
            }
        )
    return {
        "id": plan.get("id"),
        "revision": plan.get("revision"),
        "steps": steps,
        "decision_ids": [d.get("id") for d in plan.get("decisions", []) if isinstance(d, dict)],
        "issues_addressed": plan.get("issues_addressed", []),
        "truncated": True,
    }


class ContextBuilder:
    def __init__(self, artifacts: ArtifactStore, tokenizer: Tokenizer | None = None) -> None:
        self.artifacts = artifacts
        self.tokenizer = tokenizer if tokenizer is not None else ByteTokenizer()

    def build_context(
        self, run: RunState, role: str, phase: RunPhase,
        refs: list[str], limits: ContextLimits,
    ) -> ContextBundle:
        run = RunState.model_validate(run.model_dump())
        by_id = {item.id: item for item in run.evidence}
        required = sorted(set(refs))
        if any(key not in by_id for key in required):
            raise ValueError("unknown essential evidence")
        candidates = [by_id[key] for key in required]
        candidates += sorted(
            (e for e in run.evidence if e.id not in required), key=lambda e: e.id,
        )
        for evidence in candidates:
            if evidence.run_id != run.run.id or evidence.snapshot_id != run.run.snapshot_id:
                raise ValueError("stale evidence cannot enter current context")
        paths = sorted(run.snapshot.file_hashes) if run.snapshot else []
        selected_paths = list(paths[:limits.max_repo_entries])
        snapshot_metadata: dict[str, Any] | None = (
            {"id": run.snapshot.id, "manifest_hash": run.snapshot.manifest_hash,
             "commit": run.snapshot.commit_if_any, "dirty": run.snapshot.dirty,
             "file_count": len(paths),
             "excluded_patterns": run.snapshot.excluded_patterns}
            if run.snapshot else None
        )
        task_dict = run.task.model_dump(mode="json")
        essential_sources = [
            {"id": key, "locator": by_id[key].locator,
             "hash": by_id[key].content_hash,
             "status": by_id[key].status.value} for key in required
        ]
        full_plan: dict[str, Any] | None = None
        full_issues: list[dict[str, Any]] = []
        if phase != RunPhase.INDEPENDENT_ANALYSIS:
            full_plan = run.plan.model_dump(mode="json") if run.plan else None
            full_issues = [
                issue.model_dump(mode="json") for issue in run.issues
                if issue.status not in {IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.DUPLICATE}
            ]
            # Blocking issues first so truncation keeps the most important ones.
            full_issues.sort(key=lambda d: (0 if d.get("severity") == "blocking" else 1, str(d.get("id"))))

        def _dump(baseline: dict[str, Any]) -> str:
            return json.dumps(baseline, ensure_ascii=False, sort_keys=True)

        def _make_baseline(
            repo_map: list[str],
            plan: dict[str, Any] | None,
            issues: list[dict[str, Any]] | None,
            notes: list[str],
        ) -> dict[str, Any]:
            baseline: dict[str, Any] = {
                "task": task_dict,
                "snapshot": snapshot_metadata,
                "repo_map": list(repo_map),
                "essential_sources": essential_sources,
            }
            if phase != RunPhase.INDEPENDENT_ANALYSIS:
                baseline["plan"] = plan
                baseline["open_issues"] = issues if issues is not None else []
            if notes:
                baseline["baseline_notes"] = notes
            return baseline

        baseline_notes: list[str] = []
        # Level 0: full plan + full issues, shrink repo_map first.
        repo_map = list(selected_paths)
        plan_view = full_plan
        issues_view: list[dict[str, Any]] | None = full_issues if phase != RunPhase.INDEPENDENT_ANALYSIS else None
        content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))
        while repo_map and self.tokenizer.count(content) > limits.max_tokens:
            repo_map.pop()
            content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))

        # Level 1: summarize long text fields in plan/issues (keep DAG + ids).
        if self.tokenizer.count(content) > limits.max_tokens and phase != RunPhase.INDEPENDENT_ANALYSIS:
            if full_plan is not None:
                plan_view = _summarize_plan(full_plan, max_text=200)
            if full_issues:
                issues_view = [_summarize_issue(d, max_text=200) for d in full_issues]
            baseline_notes.append("plan/issues summarized to fit limit")
            content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))

        # Level 2: minimal plan/issues (ids + short claim/objective + deps).
        if self.tokenizer.count(content) > limits.max_tokens and phase != RunPhase.INDEPENDENT_ANALYSIS:
            if full_plan is not None:
                plan_view = _minimal_plan(full_plan, max_text=100)
            if full_issues:
                # Keep blocking first, cap count progressively.
                cap = max(1, len(full_issues) // 2)
                while cap >= 1:
                    candidate = [
                        _minimal_issue(d, max_text=100) for d in full_issues[:cap]
                    ]
                    test = _dump(_make_baseline(repo_map, plan_view, candidate, baseline_notes))
                    if self.tokenizer.count(test) <= limits.max_tokens or cap == 1:
                        issues_view = candidate
                        content = test
                        break
                    cap //= 2
                baseline_notes.append(f"plan/issues minimized, kept {len(issues_view or [])}/{len(full_issues)} issues")
                content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))
            else:
                content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))

        # Level 3: drop plan/issues bodies, keep only counts + ids.
        if self.tokenizer.count(content) > limits.max_tokens and phase != RunPhase.INDEPENDENT_ANALYSIS:
            if full_plan is not None:
                plan_view = {
                    "id": full_plan.get("id"),
                    "revision": full_plan.get("revision"),
                    "step_ids": [s.get("id") for s in full_plan.get("steps", []) if isinstance(s, dict)],
                    "step_count": len(full_plan.get("steps", [])),
                    "truncated": True,
                }
            if full_issues:
                issues_view = [{"id": d.get("id"), "severity": d.get("severity")} for d in full_issues[:5]]
            baseline_notes.append("plan/issues bodies dropped, kept counts only")
            content = _dump(_make_baseline(repo_map, plan_view, issues_view, baseline_notes))

        if self.tokenizer.count(content) > limits.max_tokens:
            task_size = self.tokenizer.count(_dump({"task": task_dict}))
            snap_size = self.tokenizer.count(_dump({"snapshot": snapshot_metadata}))
            ess_size = self.tokenizer.count(_dump({"essential_sources": essential_sources}))
            plan_size = self.tokenizer.count(_dump({"plan": full_plan})) if full_plan else 0
            issues_size = self.tokenizer.count(_dump({"open_issues": full_issues})) if full_issues else 0
            total = self.tokenizer.count(content)
            logger.warning(
                "ContextOverflow run=%s phase=%s total=%d limit=%d "
                "task=%d snapshot=%d essential=%d plan=%d issues=%d repo_paths=%d",
                run.run.id, phase.value, total, limits.max_tokens,
                task_size, snap_size, ess_size, plan_size, issues_size, len(repo_map),
            )
            raise ContextOverflow(
                f"task/snapshot/essential source references exceed limit "
                f"(total={total} > limit={limits.max_tokens}; "
                f"task={task_size}, snapshot={snap_size}, essential={ess_size}, "
                f"plan={plan_size}, open_issues={issues_size}, repo_paths={len(repo_map)}). "
                f"Shorten goal/requirements or raise limit "
                f"(ASTRA_MULTI_MAX_CONTEXT_BYTES, default {DEFAULT_ORCHESTRATION_MAX_TOKENS})."
            )
        selected_paths = repo_map
        included: list[str] = []
        truncated: list[str] = []
        omitted: list[str] = []
        for evidence in candidates:
            header = (
                f"\nUNTRUSTED EVIDENCE {evidence.id} [{evidence.locator}] "
                f"hash={evidence.content_hash} status={evidence.status.value}\n"
            )
            text = self._text(evidence)
            if self.tokenizer.count(content + header) > limits.max_tokens:
                if evidence.id in required:
                    truncated.append(evidence.id)
                    included.append(evidence.id)
                else:
                    omitted.append(evidence.id)
                continue
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if self.tokenizer.count(content + header + text[:middle]) <= limits.max_tokens:
                    low = middle
                else:
                    high = middle - 1
            content += header + text[:low]
            included.append(evidence.id)
            if low < len(text):
                truncated.append(evidence.id)
        return ContextBundle(
            run_id=run.run.id, snapshot_id=run.run.snapshot_id, role=role, phase=phase,
            content=content, source_ids=tuple(included),
            truncated_ids=tuple(truncated), omitted_ids=tuple(omitted),
            token_count=self.tokenizer.count(content), tokenizer=type(self.tokenizer).__name__,
            omitted_repo_paths=tuple(paths[len(selected_paths):]),
        )

    def _text(self, evidence: Evidence) -> str:
        if evidence.artifact is None:
            return ""
        return self.artifacts.read(evidence.artifact).decode("utf-8", errors="replace")
