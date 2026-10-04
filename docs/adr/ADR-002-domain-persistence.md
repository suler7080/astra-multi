# ADR-002: Canonical domain store, operation ledger and fenced run leases

**Status:** Accepted

**Date:** 2026-10-02

## Decision

Use Pydantic v2 contracts, Python stdlib SQLite and a content-addressed filesystem artifact store. Domain modules import neither LangGraph nor provider SDKs. `Run.phase` describes workflow position; `Run.status` describes progress/outcome. A greenfield run explicitly carries `snapshot_id: null`; repo runs require an immutable `Snapshot` reference.

`SQLiteStore` implements the `RunRepository` and `LeaseService` ports. The canonical aggregate includes append-only task/plan revisions, entity records and issue history. SQLite stores the aggregate as validated versioned JSON, with separate ordered event and operation ledgers. This avoids coupling P2/P3 clients to table layout; normalized read indexes can be introduced by a future versioned migration when needed.

## Mutation boundary

```text
BEGIN IMMEDIATE
  validate current lease owner/token/epoch/expiry
  find (run_id, node, logical_operation_id)
    existing + same command hash -> original operation result
    existing + different hash -> operation_conflict
  validate expected_revision and domain policy
  verify all referenced artifacts are present and hash/size match
  update aggregate (revision += 1)
  append event (sequence += 1 per run)
  append operation result
  recheck lease expiry
COMMIT
```

`BEGIN IMMEDIATE` serializes writers across threads/processes. WAL permits readers while one writer works. Foreign keys and FULL synchronous mode are enabled. Each worker owns its own connection; connections are not shared across threads. The initial create atomically writes revision 1 and event 1; later commands require a lease. API intake idempotency across new run IDs belongs to P5, rather than overloading the node-operation ledger.

The artifact store writes and fsyncs a temporary file in the destination directory, atomically replaces the SHA-256 named destination, and fsyncs the directory on POSIX before returning a reference. A database rollback may leave an unreferenced complete artifact; it cannot publish a missing/incomplete artifact reference through repository commits. Artifact garbage collection is deferred. Windows supports file fsync and same-directory replace; Windows-specific power-loss durability is not verified on the Linux test host.

## Lease and recovery

Acquire fails while a lease is live, even for the same owner name. Expired/released lease takeover issues a fresh token and increments the epoch. Heartbeat renews only a live matching lease. Release retains the epoch row and expires it. Mutations check the database lease, not the caller's copied expiry; an old worker cannot commit, heartbeat or release after takeover. Workers must heartbeat before TTL expiration and bound transaction work to the remaining TTL.

`CheckpointBridge` stores only run/task/plan references and canonical run revision. A stale execution checkpoint loads current canonical state. If a node committed but died before checkpoint save, it replays the same command and stable operation ID to retrieve the existing result, then advances its reference. It must preserve the command payload (including timestamps) across replay; reusing a key for a rebuilt different payload is rejected.

This is **idempotent domain commit**, not exactly-once execution. An external model/provider call can repeat after a crash between response and persistence. P2/P3 must make side-effecting tools idempotent or reconcile their results, and use the persisted operation result before deciding to repeat work.

## Policy boundary

Only explicit commands mutate canonical state. Blocking issue closure requires a reasoned resolution with an independent review of the new current plan, or a persisted change to a referenced requirement with actor/reason provenance. Closure retains the full issue history. Terminal runs cannot resume or acquire a new lease; continuation creates a new run. General transition commands cannot set FINAL: P4 must supply the quality service before canonical FINAL is available.

The P0 demo remains an orchestration spike; it consumes the typed domain models but its permissive fake gate and inline graph state are not the product persistence API. P3 will wire its real orchestration to `CheckpointBridge`, and P4 supplies quality/export services.

## Evidence and limits

- `tests/unit/test_domain.py`: schema round trips, invalid fixtures, references, transition tables, stale commands, issue history, provenance and pending answers.
- `tests/integration/test_storage.py`: real SQLite transactions, operation collisions/replays, migration reopen/future-version rejection, artifact failure/hash checks, lease renewal/takeover and public client restart.
- `tests/recovery/test_crash.py`: OS process kill inside mutation/event/ledger writes and after domain commit before the real LangGraph SQLite checkpoint; restart produces one canonical plan and one mutation event. Separate subprocesses contend for one lease.

Schema version and database migration version both start at 1. There is no previous canonical domain schema to upgrade yet; the P0 checkpoint database is deliberately separate. Native Windows execution and provider live tests remain outside this phase's verified evidence.
