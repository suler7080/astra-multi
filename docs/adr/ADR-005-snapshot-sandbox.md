# ADR-005 — Content-addressed snapshots and Linux Docker verification

Status: Accepted for P2, 2026-10-02.

## Decision

Use existing ArtifactStore plus a hashed manifest as the frozen repository input.
Canonical domain Snapshot/Evidence/ToolCall/ValidationResult remain in SQLite
through fenced repository mutations. Inspectors consume artifact bytes exclusively.
Double scanning detects concurrent changes; read-only analysis never means a
successful executable check.

Run untrusted commands only in an available Linux Docker target with a pinned
image and bounded resources, no network/secrets, an immutable seed mount and a
writable container copy. Explicit unavailable/timeout/cancelled results map to
NOT_RUN, never PASS. No subprocess fallback executes repository code on host.

## Consequences

Git commit alone is insufficient for dirty trees; manifests include actual bytes
and explicit exclusions. Content and provenance survive restart independently
of LangGraph/provider SDK objects. Byte/record pagination and token selection
preserve source references. Artifact garbage collection is deferred to later
retention work; failed capture may leave unreferenced content-addressed blobs.

Linux Docker is the live P2 gate. Windows is an unavailable runner profile until
native P2 implementation/testing; Linux containers do not prove Windows behavior.
Docker shares the host kernel, so this is container isolation, not a VM security
boundary. Runner capabilities and dependency installation remain explicit.

## Alternatives

Direct host subprocess: rejected because repository code could access host files,
credentials and processes. Commit-only checkout: rejected because dirty/non-Git
input is lost. Implicit host fallback or fake PASS on unavailable infrastructure:
rejected because it would misrepresent verification.

Contracts, operational limits and verification are in ../P2_CONTRACTS.md and
../spikes/P2_PHASE_REPORT.md.
