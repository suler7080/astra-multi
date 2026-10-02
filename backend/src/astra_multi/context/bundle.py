from __future__ import annotations

import json
from typing import Annotated, Protocol

from pydantic import Field

from astra_multi.domain.models import (
    Contract,
    Evidence,
    IssueStatus,
    RunPhase,
    RunState,
)
from astra_multi.domain.repositories import ArtifactStore


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


class ByteTokenizer:
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


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
        selected_paths = paths[:limits.max_repo_entries]
        snapshot_metadata = (
            {"id": run.snapshot.id, "manifest_hash": run.snapshot.manifest_hash,
             "commit": run.snapshot.commit_if_any, "dirty": run.snapshot.dirty,
             "file_count": len(paths),
             "excluded_patterns": run.snapshot.excluded_patterns}
            if run.snapshot else None
        )
        baseline = {
            "task": run.task.model_dump(mode="json"),
            "snapshot": snapshot_metadata,
            "repo_map": selected_paths,
            "essential_sources": [
                {"id": key, "locator": by_id[key].locator,
                 "hash": by_id[key].content_hash,
                 "status": by_id[key].status.value} for key in required
            ],
        }
        if phase != RunPhase.INDEPENDENT_ANALYSIS:
            baseline["plan"] = run.plan.model_dump(mode="json") if run.plan else None
            baseline["open_issues"] = [
                issue.model_dump(mode="json") for issue in run.issues
                if issue.status not in {IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.DUPLICATE}
            ]
        content = json.dumps(baseline, ensure_ascii=False, sort_keys=True)
        while selected_paths and self.tokenizer.count(content) > limits.max_tokens:
            selected_paths.pop()
            content = json.dumps(baseline, ensure_ascii=False, sort_keys=True)
        if self.tokenizer.count(content) > limits.max_tokens:
            raise ContextOverflow("task/snapshot/essential source references exceed limit")
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
