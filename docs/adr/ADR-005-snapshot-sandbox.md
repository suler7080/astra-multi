# ADR-005 — Content-addressed snapshots and sandbox verification

Status: Accepted for P2, 2026-10-03.

## Decision

Use existing ArtifactStore plus a hashed manifest as the frozen repository input.
Canonical domain Snapshot/Evidence/ToolCall/ValidationResult remain in SQLite
through fenced repository mutations. Inspectors consume artifact bytes exclusively.
Double scanning detects concurrent changes; read-only analysis never means a
successful executable check.

Run untrusted commands in available sandbox targets:
- **Linux Docker**: pinned image and bounded resources, no network/secrets, immutable seed mount and writable container copy
- **Windows Native**: subprocess with minimal environment, bounded output, timeout/cancellation support

Explicit unavailable/timeout/cancelled results map to NOT_RUN, never PASS.
No subprocess fallback executes repository code on host.

## Consequences

Git commit alone is insufficient for dirty trees; manifests include actual bytes
and explicit exclusions. Content and provenance survive restart independently
of LangGraph/provider SDK objects. Byte/record pagination and token selection
preserve source references. Artifact garbage collection is deferred to later
retention work; failed capture may leave unreferenced content-addressed blobs.

Linux Docker provides strong isolation with cgroup quotas, no network, and container
filesystem isolation. Windows subprocess provides process isolation with minimal
environment variables and bounded output. Both platforms are now verified and
supported.

Docker shares the host kernel, so Linux Docker is container isolation, not a VM
security boundary. Windows subprocess provides process-level isolation; filesystem
access is bounded to the materialized snapshot directory.

Runner capabilities and dependency installation remain explicit.

## Alternatives

Direct host subprocess without sandbox: rejected because repository code could access
host files, credentials and processes. Commit-only checkout: rejected because dirty/non-Git
input is lost. Implicit host fallback or fake PASS on unavailable infrastructure:
rejected because it would misrepresent verification. Windows-only implementation:
rejected because cross-platform support is required.

Contracts, operational limits and verification are in ../P2_CONTRACTS.md and
../spikes/P2_PHASE_REPORT.md.
