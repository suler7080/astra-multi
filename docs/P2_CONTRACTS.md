# P2 snapshot, tools, evidence and sandbox contracts

P2.1–P2.5 are implemented for the selected **Linux Docker** execution target.
Native Windows P2 capture/junction/container behavior is **NOT_RUN**; selecting
the Windows runner returns unavailable. Earlier native Windows P1 results do
not establish P2 compatibility.

## Frozen input

`SnapshotStore.capture(root, SelectionPolicy(), attempts=2)` returns
`SnapshotRef(snapshot, manifest)`. The domain Snapshot is canonical; its ID
identifies manifest content. Origin path, Git HEAD/dirty metadata and timestamps
are separate from that content identity. The manifest contains policy,
file-to-artifact mappings, executable bits and excluded path/reason mappings.
Directories excluded as a unit are recorded once; their children are not scanned.

Git selection includes tracked and optionally untracked files, respects Gitignore
by default, and captures actual dirty bytes. Non-Git directories use the same
quotas and exclusions. Git metadata errors are not silently called non-Git.
Two scans compare hashes, metadata, exclusions, HEAD and status; inconsistent
capture retries at most five times then raises `SnapshotError`.
Default quotas: 10,000 files, 4 MiB/file, 64 MiB total.

Readers use verified content-addressed artifacts exclusively. They never consult
the source repository. Relative POSIX paths only; absolute paths, traversal,
backslashes, colons and NUL are rejected. Links/reparse paths are excluded.
POSIX file opens traverse directory descriptors with O_NOFOLLOW. Windows uses
portable link/resolve and identity checks, pending native P2 verification.
Case-folding collisions fail rather than creating ambiguous Windows paths.

## Tools and documents

`ToolBroker(run, snapshots, snapshot, documents=None)` binds one run and snapshot.
Greenfield uses `snapshot=None`; repo actions fail explicitly.
`execute(ToolRequest)` supports read/list/literal-search/inspect/document.
Nonempty repo paths scope list/search/inspect to a file or directory prefix.
Inspection reports declared dependencies/scripts/Make targets and command
candidates; candidates are never automatically executed.

`ToolRequest`: run_id, snapshot_id, call_id, action, path/query, offset/limit,
match_offset/max_matches. Reusing a call ID with another request is an error;
repeating the identical request on the same broker returns the captured result.

`ToolResult`: request, request_hash, source_type, locator, sources (full file hashes and line
ranges), captured_at, content_hash, output_ref, page, next_match, media_type.
Read range metadata lives in `page.start/end`; source ranges cover the full
underlying file or matching lines. Offsets are bytes, line indices are one-based.
`page.text` is UTF-8 replacement-decoded presentation; use output_ref for exact
bytes (including binary data or a codepoint crossing a page boundary).

Outputs are retained in artifacts; pages are at most 65,536 bytes and include
total_bytes, next_offset and truncation. `broker.page(output_ref, offset, limit)`
only accepts outputs previously produced by that bound broker. After restart,
the trusted controller can recover artifacts through persisted ToolCall records.
Search returns at most 1,000 hits per request, clips displayed lines to 4,096
characters with explicit line_truncated, and resumes via next_match. Every hit
retains the original file hash/line, enabling a subsequent exact read.

`DocumentFetcher(DocumentPolicy(scopes=...))` is disabled by default. HTTPS
origin/path allowlist; redirects revalidated individually; credentials, queries,
fragments and encoded/traversal paths rejected. Local HTTP is only an explicit
loopback fixture option. Default 10 s/read timeout, 1 MiB response and three
redirects. URL, actual capture time, hash and fetched bytes survive persistence.
URLs, files, pages and output logs are **untrusted data**, never controller rules,
budget configuration, credential instructions or executable command selection.

## Evidence and context

`EvidenceLedger(repository, artifacts, lease)` commits P1 AddRecord operations
with revision/lease fencing and deterministic record IDs. Re-recording the same
captured result is idempotent, including recovery between record commits.
ToolCall.request_hash hashes the request; output hashes identify captured bytes.
Read/search/inspection/document evidence is always **NOT_RUN**.

`EvidenceRef` means the canonical domain Evidence ID plus its artifact/content
hash, snapshot_id and tool_call_id. No second evidence schema is introduced.
`ledger.claim(text, evidence_ids, claim_id)` creates a fact only with nonempty,
known references from this run/snapshot. Summaries have no separate fact-creation
path: keep original IDs and supply original evidence.

`ContextBuilder(artifacts, tokenizer).build_context(run, role, phase, refs, limits)`
returns ContextBundle: content, run/snapshot/role/phase, source_ids, truncated_ids,
omitted_ids, omitted_repo_paths, token_count and tokenizer name.
Unknown essential references and stale evidence raise errors.
Task and essential source ID/locator/hash metadata are retained; if they cannot
fit, ContextOverflow is explicit. Body content and repository map are shortened
with selection metadata. First independent analyses receive identical facts;
private role analyses/transcripts are not included. Later contexts include the
current plan and open issues.

Tokenizer is an injected `count(text)->int` protocol. Default ByteTokenizer is
a conservative byte budget; P3 adapters should inject their supported tokenizer.
Tests use a deterministic character tokenizer. Do not claim exact model tokens
without an adapter tokenizer.

## Sandbox jobs

`DockerRunner(snapshots, work_root, SandboxProfile()).probe()` checks Linux
daemon/version and local image identity. No automatic image pull and no host-code
fallback. Provision image explicitly:

```sh
docker pull python@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb
```

Default profile: Linux, pinned Python OCI digest, 15 s execution limit, 1 CPU,
256 MiB RAM/no swap, 64 PIDs, 64 MiB writable workspace, 8 MiB /tmp, 64 KiB logs,
network=none. Command is an argv tuple, not a host shell command.
Docker creates a container, then starts/attaches; controls have 15 s bounded
timeouts. Container name/job ID are generated by the runner.

The snapshot is materialized into a fresh host job directory, mounted read-only
at /seed and copied inside /work/repo. Container root is read-only; execution
uses UID/GID 65534, all capabilities dropped, no-new-privileges, no Docker socket,
no provider key/environment mounts. Only the trusted Docker client runs on host.
Writable tmpfs and output collection have explicit quotas; logs beyond the cap
are discarded and output_total_bytes/output_truncated record that loss.
Known secret values are forbidden in command argv and redacted from output
before artifact writes, including a secret crossing the output limit.

`execute(snapshot, JobRequest, cancel=Event())` synchronously transitions from
capture/materialization to container execution and terminal JobResult. An
optional on_running Event indicates observed container running state.
Cancellation/timeout kills the container; force removal and a successful Docker
inventory query confirm absence. Cleanup failure prevents PASS.

JobResult persists run/snapshot/call/job IDs, target/image/engine, redacted command,
expected/actual/exit code, timestamps, log artifact, quotas, output accounting and
cleanup. `ledger.record_job(job)` persists ToolCall, report Evidence and
ValidationResult. Mapping:

| Job status | Validation | Meaning |
|---|---|---|
| passed | PASS | Executed in available target, exit 0, cleanup confirmed |
| failed | FAIL | Executed, nonzero exit |
| timeout/cancelled | NOT_RUN | Incomplete verification; partial logs retained |
| unavailable | NOT_RUN | Missing/unsupported target/image/transport or unconfirmed cleanup |

NOT_RUN ValidationResult has no actual/exit/executed_at as required by P1.
Actual lifecycle diagnostics remain in JobResult/report evidence; an unavailable
ToolCall has no finished_at/exit because executable completion did not occur.
The runner needs a Python-compatible image for bootstrap and command tools
present inside that image. It does not install repository dependencies or infer
commands from untrusted documentation. RequestHash for sandbox records hashes
request metadata, separately from the result artifact.

## Demo and P3 fixtures

From backend, use a workspace outside the inspected source:

```sh
.venv/bin/python -m astra_multi.p2_demo tests/support/p2_repo .local/p2-demo -- python -m unittest fixture_test -v
ASTRA_P2_LIVE_SANDBOX=1 .venv/bin/python -m pytest tests/ -q
```

Demo persists capture → list/inspect → cited claim → independent context →
verification, releases the lease, reopens SQLite, verifies report integrity and
prints the evidence index. SQLite and its adjacent artifact directory are the
restart handoff, not process-local provider/runtime state.

Fixtures: tests/support/p2_repo (standard-library Python repo),
unit/test_snapshots.py (Git/dirty/non-Git/race/path/quota),
unit/test_tool_broker.py (pagination/search/local HTTP and injection data),
integration/test_evidence_context.py (restart/freshness/token limits),
integration/test_sandbox.py (live Docker plus unavailable targets), and
integration/test_p2_demo.py (source hashes/claim traceability).
