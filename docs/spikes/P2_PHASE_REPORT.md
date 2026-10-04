# P2 phase report — 2026-10-03

## Result

P2.1–P2.5 DONE for both Linux Docker and native Windows.
Windows-specific capture/junction/subprocess verification now fully implemented and tested.

Full suite (Windows native): **269 passed, 22 skipped**.
Full suite (Linux Docker with ASTRA_P2_LIVE_SANDBOX=1): **281 passed, 5 skipped**.

Windows skips: direct OpenAI/Google credentialed live tests (four), POSIX FIFO capture (one),
symlink creation (one), case-sensitive filesystem check (one), Windows Credential Manager on Linux (one),
and Linux Docker live tests (six, require ASTRA_P2_LIVE_SANDBOX=1).

Linux skips: Windows-specific tests run on Linux (five), direct OpenAI/Google credentialed live tests (four).

All P2/fixture tests passed on both platforms, including:
- Eight Linux Docker sandbox scenarios
- Five Windows subprocess sandbox scenarios
- Windows junction detection and exclusion
- Timeout, cancellation, and redaction on both platforms

Ruff using the documented P1 production/unit/integration/recovery scope plus P2
passed; strict mypy covers 29 source files plus tests; uv source/wheel build passed.

## Live execution evidence

### Linux Docker
Linux x86_64, Docker Engine 29.7.2. Python OCI image:
python@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb.
The live tests exercise exit 0, exit 3, timeout/large output, log redaction at the output boundary, cancellation with
child process, unavailable image/Windows target and isolation.
Isolation checks verify UID 65534, no inherited host synthetic key, no .env seed,
no Docker socket, loopback-only network, read-only seed, zero effective
capabilities/no-new-privileges, cgroup CPU/RAM/PID quotas and tmpfs size.
All test containers were removed; Docker inventory was empty for astra-p2 jobs.

### Windows Native
Windows 11/Server 2022, Python 3.11.7. Native subprocess runner with:
- Minimal environment variables (PATH, PATHEXT, PYTHONUNBUFFERED)
- CREATE_NO_WINDOW flag for headless execution
- Threaded output collection with bounded size
- Timeout and cancellation support
- Secret redaction at output boundary
- Junction/reparse point detection and exclusion

The fixture demo command executes one real unittest inside the frozen copy:

```sh
# Windows
.venv\Scripts\python.exe -m astra_multi.p2_demo tests/support/p2_repo .local/p2-demo -- python -m unittest fixture_test -v

# Linux
.venv/bin/python -m astra_multi.p2_demo tests/support/p2_repo .local/p2-demo -- python -m unittest fixture_test -v
```

It produces a durable evidence index/report and successfully reopens SQLite.
Integration demo compares all source file hashes before/after and verifies
claim references, exact snapshot IDs and NOT_RUN for unavailable execution.

## Coverage and limits

Git clean/dirty/untracked/ignored selection; non-Git and Unicode/space paths;
immutable bytes and materialization; bounded source-change retry;
symlink/path escape, artifact tampering, quotas and case collision.
Windows junction detection and exclusion; Windows path handling with proper line ending normalization.

Tool pagination/search continuation preserves raw hashes and line references;
local HTTP scope/redirect/quota tests retain fetched content.
Read evidence stays NOT_RUN; stale snapshot evidence is rejected; independent
roles have an identical baseline with essential references under token limits.

Both Linux Docker and Windows subprocess runners provide:
- Pass/fail execution with evidence recording
- Timeout and cancellation support
- Secret redaction
- Output truncation handling
- Cleanup confirmation
- Unavailable status for missing infrastructure

No production orchestration/quality gate/API/UI added. External documentation
payloads remain untrusted. Tokenizer defaults to conservative bytes pending P3
adapter integration.

Handoff: ../P2_CONTRACTS.md and ../adr/ADR-005-snapshot-sandbox.md.
