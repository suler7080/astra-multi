# P2 phase report — 2026-10-02

## Result

P2.1–P2.5 DONE for Linux Docker. Native Windows P2 runner is unavailable;
Windows-specific capture/junction/container checks remain NOT_RUN.

Full suite: **281 passed, 5 skipped** with ASTRA_P2_LIVE_SANDBOX=1.
The five skips are direct OpenAI/Google credentialed live tests (four) and
Windows Credential Manager on Linux (one).
All 28 new P2/fixture tests passed, including eight sandbox scenarios and a file-to-FIFO capture race.
Ruff using the documented P1 production/unit/integration/recovery scope plus P2
passed; strict mypy covers 29 source files; uv source/wheel build passed.
The repository-wide spike lint command also exposes existing spike-only lint
issues; those files are unchanged by P2. The build uses documented uv build,
since python -m build is not installed in this venv.

## Live execution evidence

Linux x86_64, Docker Engine 29.7.2. Python OCI image:
python@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb.
The live tests exercise exit 0, exit 3, timeout/large output, log redaction at the output boundary, cancellation with
child process, unavailable image/Windows target and isolation.
Isolation checks verify UID 65534, no inherited host synthetic key, no .env seed,
no Docker socket, loopback-only network, read-only seed, zero effective
capabilities/no-new-privileges, cgroup CPU/RAM/PID quotas and tmpfs size.
All test containers were removed; Docker inventory was empty for astra-p2 jobs.

The fixture demo command executes one real unittest inside the frozen copy:

```sh
.venv/bin/python -m astra_multi.p2_demo tests/support/p2_repo .local/p2-demo -- python -m unittest fixture_test -v
```

It produces a durable evidence index/report and successfully reopens SQLite.
Integration demo compares all source file hashes before/after and verifies
claim references, exact snapshot IDs and NOT_RUN for unavailable execution.

## Coverage and limits

Git clean/dirty/untracked/ignored selection; non-Git and Unicode/space paths;
immutable bytes and materialization; bounded source-change retry;
symlink/path escape, artifact tampering, quotas and case collision.
Tool pagination/search continuation preserves raw hashes and line references;
local HTTP scope/redirect/quota tests retain fetched content.
Read evidence stays NOT_RUN; stale snapshot evidence is rejected; independent
roles have an identical baseline with essential references under token limits.

No production orchestration/quality gate/API/UI added. External documentation
payloads remain untrusted. Tokenizer defaults to conservative bytes pending P3
adapter integration. Windows P2 behavior is not inferred from earlier P1 results.

Handoff: ../P2_CONTRACTS.md and ../adr/ADR-005-snapshot-sandbox.md.
