from typing import Annotated, Literal

from pydantic import Field

from astra_multi.domain.models import ID, UTC, ArtifactRef, Contract, Hash, Text


class ToolRequest(Contract):
    run_id: ID
    snapshot_id: ID | None
    call_id: ID
    action: Literal["read", "list", "search", "inspect", "document"]
    path: str = ""
    query: str = ""
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=65536)] = 8192
    match_offset: Annotated[int, Field(ge=0)] = 0
    max_matches: Annotated[int, Field(ge=1, le=1000)] = 100


class SourceRef(Contract):
    locator: Text
    content_hash: Hash
    snapshot_id: ID | None
    line_start: int | None = None
    line_end: int | None = None


class OutputPage(Contract):
    text: str
    start: int
    end: int
    total_bytes: int
    next_offset: int | None
    truncated: bool


class ToolResult(Contract):
    request: ToolRequest
    request_hash: Hash
    source_type: Literal["repo", "document"]
    locator: Text
    content_hash: Hash
    output_ref: ArtifactRef
    page: OutputPage
    sources: tuple[SourceRef, ...]
    captured_at: UTC
    media_type: str = "text/plain"
    next_match: int | None = None
