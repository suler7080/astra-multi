from __future__ import annotations

import json
import tomllib
from pathlib import PurePosixPath

from pydantic import JsonValue, TypeAdapter

from astra_multi.context.snapshots import (
    SnapshotError,
    SnapshotRef,
    SnapshotStore,
    digest,
    safe_path,
)
from astra_multi.domain.models import ArtifactRef, Run, utc_now

from .contracts import OutputPage, SourceRef, ToolRequest, ToolResult
from .documents import DocumentFetcher


class ToolBroker:
    def __init__(
        self, run: Run, snapshots: SnapshotStore, snapshot: SnapshotRef | None,
        documents: DocumentFetcher | None = None,
    ) -> None:
        if run.snapshot_id != (snapshot.snapshot.id if snapshot else None):
            raise SnapshotError("broker snapshot does not match run")
        self.run = run
        self.snapshots = snapshots
        self.snapshot = snapshot
        self.documents = documents
        self._results: dict[str, ToolResult] = {}

    def page(self, output: ArtifactRef, offset: int, limit: int) -> OutputPage:
        if not any(result.output_ref == output for result in self._results.values()):
            raise ValueError("output was not produced by this bound broker")
        return self._page(output, offset, limit)

    def _page(self, output: ArtifactRef, offset: int, limit: int) -> OutputPage:
        if not 0 <= offset <= output.size or not 1 <= limit <= 65536:
            raise ValueError("invalid output range")
        content = self.snapshots.artifacts.read(output)
        end = min(offset + limit, len(content))
        return OutputPage(
            text=content[offset:end].decode("utf-8", errors="replace"),
            start=offset, end=end, total_bytes=len(content),
            next_offset=end if end < len(content) else None,
            truncated=offset != 0 or end < len(content),
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        request = ToolRequest.model_validate(request.model_dump())
        if (
            request.run_id != self.run.id
            or request.snapshot_id != self.run.snapshot_id
        ):
            raise ValueError("tool request outside bound run/snapshot")
        if request.call_id in self._results:
            cached = self._results[request.call_id]
            if cached.request != request:
                raise ValueError("call ID reused for a different request")
            return cached
        captured = utc_now()
        sources: list[SourceRef] = []
        source_type = "repo"
        media_type = "text/plain"
        next_match = None
        if request.action == "document":
            if self.documents is None:
                raise ValueError("documentation fetch unavailable")
            locator, content, media_type = self.documents.fetch(request.path)
            source_type = "document"
        else:
            ref = self.snapshot
            if ref is None:
                raise SnapshotError("greenfield context has no repository")
            manifest = self.snapshots.manifest(ref)
            if request.path:
                safe_path(request.path)
            files = {
                name: entry for name, entry in manifest.files.items()
                if not request.path or name == request.path or name.startswith(request.path + "/")
            }
            locator = f"snapshot://{ref.snapshot.id}/{request.path}"
            if request.action == "read":
                content = self.snapshots.read(ref, request.path)
                sources.append(SourceRef(
                    locator=locator,
                    content_hash=manifest.files[request.path].artifact.content_hash,
                    snapshot_id=ref.snapshot.id, line_start=1,
                    line_end=len(content.splitlines()),
                ))
            elif request.action == "list":
                content = json.dumps(
                    {p: e.model_dump(mode="json") for p, e in files.items()},
                    ensure_ascii=False, sort_keys=True,
                ).encode()
            elif request.action == "search":
                if not request.query:
                    raise ValueError("search requires a nonempty literal query")
                hits: list[dict[str, JsonValue]] = []
                matched = 0
                for name, entry in files.items():
                    raw = self.snapshots.artifacts.read(entry.artifact)
                    if b"\x00" in raw:
                        continue
                    for line, text in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                        if request.query in text:
                            matched += 1
                            if matched <= request.match_offset:
                                continue
                            if len(hits) >= request.max_matches:
                                next_match = matched - 1
                                break
                            source = SourceRef(
                                locator=f"snapshot://{ref.snapshot.id}/{name}",
                                content_hash=entry.artifact.content_hash,
                                snapshot_id=ref.snapshot.id, line_start=line, line_end=line,
                            )
                            sources.append(source)
                            hits.append({
                                "path": name, "line": line,
                                "text": text[:4096], "line_truncated": len(text) > 4096,
                            })
                    if next_match is not None:
                        break
                content = json.dumps(hits, ensure_ascii=False).encode()
            else:
                inspected: dict[str, JsonValue] = {}
                for name, entry in files.items():
                    if PurePosixPath(name).name not in {"pyproject.toml", "package.json", "Makefile"}:
                        continue
                    raw = self.snapshots.artifacts.read(entry.artifact)
                    try:
                        if name.endswith("pyproject.toml"):
                            project = tomllib.loads(raw.decode()).get("project", {})
                            if not isinstance(project, dict):
                                raise ValueError("project must be a table")
                            dependencies = project.get("dependencies", [])
                            if not isinstance(dependencies, list) or not all(
                                isinstance(item, str) for item in dependencies
                            ):
                                raise ValueError("dependencies must be strings")
                            inspected[name] = {
                                "dependencies": dependencies,
                                "test_command_candidate": ["python", "-m", "pytest"],
                            }
                        elif name.endswith("package.json"):
                            inspected[name] = TypeAdapter(JsonValue).validate_json(raw)
                        else:
                            inspected[name] = {
                                "test_targets": [
                                    line.split(":")[0] for line in raw.decode().splitlines()
                                    if line.startswith(("test:", "check:"))
                                ],
                            }
                    except (ValueError, UnicodeError):
                        inspected[name] = {"error": "invalid dependency manifest"}
                    sources.append(SourceRef(
                        locator=f"snapshot://{ref.snapshot.id}/{name}",
                        content_hash=entry.artifact.content_hash,
                        snapshot_id=ref.snapshot.id,
                    ))
                content = json.dumps(inspected, ensure_ascii=False).encode()
                media_type = "application/json"
        output = self.snapshots.artifacts.put(content)
        if source_type == "document":
            sources.append(SourceRef(
                locator=locator, content_hash=output.content_hash, snapshot_id=None,
            ))
        result = ToolResult(
            request=request, request_hash=digest(request.model_dump_json().encode()),
            source_type="document" if source_type == "document" else "repo",
            locator=locator, content_hash=output.content_hash, output_ref=output,
            page=self._page(output, request.offset, request.limit),
            sources=tuple(sources), captured_at=captured, media_type=media_type,
            next_match=next_match,
        )
        self._results[request.call_id] = result
        return result
