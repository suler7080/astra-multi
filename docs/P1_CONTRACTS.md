# P1 — Public domain and persistence contracts

## Imports and schema version

```python
from astra_multi.domain.models import TaskSpec, Run, RunState, Issue, PlanRevision
from astra_multi.domain.commands import AddRecord, CommitPlan, ChangeIssue
from astra_multi.domain.repositories import RunRepository, LeaseService, ArtifactStore
from astra_multi.persistence import SQLiteStore, CheckpointBridge, FileArtifactStore
```

Domain imports require Pydantic v2 only. All entities have explicit stable `id`, `schema_version: 1`, and UTC `created_at`. IDs are nonempty ASCII identifiers; callers can use UUIDs or their own stable IDs. Defaults generate UTC creation times, never IDs. Aware timestamps are normalized to UTC; naive timestamps, unknown fields, unsupported schema versions, blank required text and invalid enums are rejected. Serialized domain records use `model_dump_json()` / `model_validate_json()`.

Generate machine-readable JSON Schema and valid/invalid samples:

```sh
cd backend
.venv/bin/python -m astra_multi.domain.export_contracts .local/contracts
```

`schemas.json` includes TaskSpec, Run, Snapshot, Claim, Evidence, Proposal, Issue, Decision, PlanRevision/Step, ToolCall, ModelCall, Event, Question, ValidationResult, BudgetReservation, OperationRecord, ArtifactRef, CheckpointRef, Lease and RunState. `samples.json` includes repo/greenfield runs and invalid run payloads. Checked-in exports are [contracts/schemas.json](contracts/schemas.json) and [contracts/samples.json](contracts/samples.json); regenerate through the exporter, not by hand.

## References and revisions

| Reference | Rule |
|---|---|
| Run task | `task_id` immutable; `task_revision` matches current task |
| Run snapshot | repo requires snapshot, greenfield requires explicit null; immutable within a run |
| Run revision | starts at 1, every successful mutation increments once |
| Task revision | starts at 1, increments consecutively; changes retain actor/reason provenance |
| Plan revision | starts at 1, `based_on_revision = revision - 1`, references current requirements and run snapshot |
| Entity IDs | unique across a run's entity collections; same step ID may persist across plan revisions |
| Requirement/step/evidence/claim/tool/issue refs | must exist in canonical aggregate; historical issues may reference historical requirements |
| Plan dependencies | existing step IDs, no cycle; steps have objective, deliverables, validation and completion criteria |

All commands carry `expected_revision`, `node`, `logical_operation_id`, `actor`. `expected_revision` is the **run aggregate revision**, not the plan revision. `Proposal.base_revision` and `Issue.based_on_revision` are **plan** revisions, where 0 means no candidate yet. Stale command or plan/task base raises `RevisionConflict` and writes no event.

Validation status is NOT_RUN/PASS/FAIL. NOT_RUN cannot contain execution results. PASS/FAIL require expected/actual, exit code, tool ID and execution timestamp; referenced tool must be completed with matching exit code. PASS requires zero exit code. These contracts do not establish semantic correctness; P4 evaluates quality.

## Repository and lease APIs

```python
class RunRepository(Protocol):
    def create(self, task: TaskSpec, run: Run, snapshot: Snapshot | None = None) -> RunState: ...
    def load(self, run_id: str) -> RunState: ...
    def commit(self, run_id: str, command: Mutation, lease: Lease) -> OperationRecord: ...
    def events(self, run_id: str, after: int = 0) -> list[Event]: ...
    def operation(self, run_id: str, node: str, logical_operation_id: str) -> OperationRecord | None: ...

class LeaseService(Protocol):
    def acquire(self, run_id: str, owner: str, ttl: float = 30) -> Lease: ...
    def heartbeat(self, lease: Lease, ttl: float = 30) -> Lease: ...
    def release(self, lease: Lease) -> None: ...

class ArtifactStore(Protocol):
    def put(self, content: bytes) -> ArtifactRef: ...
    def read(self, ref: ArtifactRef) -> bytes: ...
```

`SQLiteStore(Path(workspace) / "domain.sqlite")` creates storage/migration version 1 and a sibling artifacts directory. Use a context manager or `close()`. `load()` of an unknown run raises `KeyError`; duplicate create violates the SQLite primary key. Each thread/process opens its own store. Consumers use the protocols and never access `connection` or private helpers (tests may inspect the database).

Mutations: `AddRecord`, `CommitPlan`, `ChangeIssue`, `AnswerQuestion`, `ReviseTask`, `TransitionRun`. New records are immutable; a new tool/model call has its own ID. AddRecord rejects preclosed issues and preanswered questions, so lifecycle commands cannot be bypassed.

Lease acquire returns owner, unguessable token, epoch and UTC expiry. Heartbeat/release require the current live owner/token/epoch. A takeover increments epoch even when the owner name is reused. All commit paths require the current lease, including replay paths; a lost worker can still read operation results. `LeaseLost`, `InvalidState`, `RevisionConflict`, `OperationConflict` are public domain errors for application/API mapping.

## Run transition table

| Current phase | Next phases while RUNNING |
|---|---|
| INTAKE | SNAPSHOT, INDEPENDENT_ANALYSIS (greenfield/spike shortcut) |
| SNAPSHOT | INVESTIGATE |
| INVESTIGATE | INDEPENDENT_ANALYSIS |
| INDEPENDENT_ANALYSIS | PROPOSE |
| PROPOSE | REVIEW |
| REVIEW | VERIFY, REVISE |
| VERIFY | REVISE |
| REVISE | QUALITY_GATE |
| QUALITY_GATE | REVIEW, EXPORT |
| EXPORT | none |

From any RUNNING phase, WAITING_FOR_INPUT requires a pending question and retains phase. Resume to RUNNING retains phase and requires all blocking answers; answers carry expected revision and persist actor/timestamp. PARTIAL/FAILED/CANCELLED retain current phase and require a stop reason. Terminal statuses are immutable. FINAL is rejected by general transitions until P4's quality service supplies the full gate contract.

## Issue lifecycle

| Current | Allowed next statuses |
|---|---|
| open | investigating, rejected, duplicate |
| investigating | proposed_resolution, rejected, duplicate |
| proposed_resolution | investigating, resolved, rejected |
| resolved / rejected / duplicate | none |

A new issue needs claim, impact, suggested resolution and either evidence IDs or a verification request. Resolution/rejection needs a nonempty reason and resolution. Proposed resolution also carries its proposed resolution. A blocking closure additionally needs:

1. The new **current** plan addresses the issue, is based on current requirements, and has a revision newer than the issue's base; resolution includes PASS, reviewer distinct from the closing actor, and a review note; or
2. `requirement_change` exactly matches persisted task-change provenance and at least one referenced requirement changed or was removed.

Every transition appends history with actor/time/reason/resolution/link. Severity cannot be updated by a command. Duplicate links directly to another canonical issue (no self-link/chains); a blocking duplicate must point to a blocking issue, preserving the blocker for the gate.

## Event envelope and operation ledger

```json
{
  "schema_version": 1,
  "id": "EVENT-ID",
  "run_id": "RUN-ID",
  "sequence": 2,
  "type": "commit_plan",
  "actor": "planner",
  "revision": 2,
  "payload": {"node": "revise", "logical_operation_id": "candidate-1", "result": {"plan_id": "PLAN-1", "plan_revision": 1}},
  "payload_ref": null,
  "timestamp": "2026-10-02T00:00:00Z",
  "created_at": "2026-10-02T00:00:00Z"
}
```

Events are ordered per run, beginning with run_created at sequence 1. Event sequence and aggregate revision are independent contracts even though P1 emits one event per mutation. `events(after=N)` is an ordered incremental read suitable for P5 SSE.

Unique operation key is `(run_id, node, logical_operation_id)`. OperationRecord contains the command hash, committed run revision, event sequence and small result references. Exact retry returns the original record **before** stale-revision checking. Same key with different payload raises OperationConflict. Preserve original timestamps and command payload across replay. Domain mutation, event and operation are one transaction; external calls are not covered by that transaction.

## Checkpoint and artifacts

`CheckpointRef` contains only `run_id`, run `revision`, `task_id`, `task_revision`, optional `plan_id` and schema version. `CheckpointBridge.load(ref)` reads canonical state even if the checkpoint lags; future/unknown refs are rejected. `commit(ref, command, lease)` returns `(OperationRecord, latest_ref)`. Save that reference in LangGraph; never copy canonical plans into production graph checkpoints.

`ArtifactRef` is SHA-256 plus byte size; storage resolves the hash under its configured root, not a supplied arbitrary path. File creation completes before a commit can publish the reference. Read verifies hash/size. Keep artifacts until references are removed through a future retention policy; rollback orphans may be cleaned later. Do not write secrets into artifacts or redacted arguments.

## Verification commands

Linux, from backend:

```sh
.venv/bin/ruff check src/astra_multi/domain src/astra_multi/persistence src/astra_multi/persistence_demo.py src/astra_multi/schemas.py src/astra_multi/fake_model.py src/astra_multi/workflow.py tests/unit tests/integration tests/recovery
.venv/bin/mypy
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m astra_multi.persistence_demo .local/new-client-workspace
.venv/bin/python -m astra_multi.domain.export_contracts .local/contracts
uv build --python .venv/bin/python
```

On Windows use `.venv\Scripts\python.exe`, `.venv\Scripts\ruff.exe`, `.venv\Scripts\mypy.exe`. The sample client requires a fresh workspace (fixed fixture IDs). Tests use temporary workspaces, real SQLite and subprocesses. At each durability boundary the parent requests an abrupt OS kill from the actual interpreter and waits for subprocess completion, bypassing transaction/context-manager cleanup. This also covers Windows venv launchers that spawn an interpreter child. WAL/FULL and the committed/replayed revision assertions remain in force. See [implementation status](../IMPLEMENTATION_STATUS.md) for native Windows results. Four existing live-provider tests require separate OpenAI/Google keys. P2/P3 can start against these public ports without importing the storage implementation or any SDK model.
