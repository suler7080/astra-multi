# ADR-001: Runtime Selection — LangGraph

**Status:** Accepted  
**Date:** 2026-10-02  
**Decision:** Use LangGraph 0.6.11 as the orchestration runtime for Astra Multi.

## Context

PLAN.md §3.3 requires the spike to prove: fan-out independent analysis, fan-in with stable ordering, checkpoint on disk, interrupt/resume, bounded loop, stream events, multi-provider adapter, and recovery after kill.

Four options were evaluated (PLAN.md §3.1):
1. **LangGraph** — stateful graph, persistence, streaming, interrupt
2. **AutoGen AgentChat** — agent teams, group chat, state/termination
3. **CrewAI Flows** — event-driven, structured state, routing
4. **Custom runtime** — full control, high implementation cost

## Spike Evidence

All tests run on: Windows NT 10.0.26200.0, Python 3.11.7, LangGraph 0.6.11.

| Capability | Result | Test |
|---|---|---|
| Fan-out parallel analysis | PASS | `test_planner_marker_not_in_reviewer_analysis` — planner/reviewer run independently |
| Fan-in deterministic merge | PASS | `test_analyses_sorted_by_role` — custom reducer sorts by role name |
| Checkpoint on disk (SQLite) | PASS | `test_checkpoint_saves_and_restores_state`, `test_checkpoint_db_has_records` |
| Interrupt/resume | PASS | `test_interrupt_pauses_and_resume_continues` — `interrupt()` + `Command(resume=...)` |
| Interrupt survives restart | PASS | `test_interrupt_persists_across_restart` — new process, same DB |
| Bounded loop | PASS | `test_respects_max_rounds` — conditional edge with round counter |
| Stream events | PASS | `test_stream_updates_observable`, `test_streaming_produces_updates` |
| Quality gate (unresolved blocker → PARTIAL) | PASS | `test_unresolved_blocker_fails_gate` |
| No duplicate plan on restart | PASS | `test_restart_same_thread_no_duplicate_plan` |
| No duplicate issues | PASS | `test_no_duplicate_issues_across_checkpoint` |
| Multi-provider adapter shape | PASS | Error routing and classification verified for OpenAI + Google |
| End-to-end fake workflow | PASS | `test_happy_path` — intake→analysis→propose→review→revise→gate→export |

**Total: 25 tests passed, 4 skipped (live provider tests — BLOCKED, no API keys).**

## Decision

**Accept LangGraph** as orchestration runtime because:

1. All 12 capabilities in PLAN.md §3.3 have been demonstrated or are feasible.
2. The `StateGraph` API maps naturally to the workflow phases.
3. `SqliteSaver` provides checkpoint persistence compatible with Windows (with WAL mode).
4. `interrupt()`/`Command(resume=...)` provides clean human-in-the-loop without custom state machines.
5. Fan-out via multiple edges + custom reducer gives deterministic merge ordering.
6. Bounded loops via conditional edges + state counter are straightforward.
7. Stream mode `"updates"` provides real-time node-level observability.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| LangGraph API changes | Pin version 0.6.11 in lockfile; adapter boundary isolates graph details |
| SQLite locking on Windows | WAL mode + busy_timeout; single writer pattern |
| `from_conn_string` is context manager, not direct call | Use `SqliteSaver(conn)` directly with managed connection |
| LangChainPendingDeprecationWarning on `allowed_objects` | Monitor — cosmetic, no functional impact |

## Alternatives Not Chosen

- **AutoGen AgentChat**: Viable alternative. Would require more custom work for evidence ledger and quality gates. Consider if LangGraph proves limiting in P3.
- **CrewAI Flows**: Viable alternative. Less community adoption than LangGraph/AutoGen.
- **Custom runtime**: Only if LangGraph fails in production scenarios. Cost too high for MVP.

## Dependencies Locked

See `backend/requirements.lock` for pinned versions. Key packages:
- `langgraph==0.6.11`
- `langgraph-checkpoint==2.1.2`
- `langgraph-checkpoint-sqlite==2.0.11`
- `pydantic==2.13.5`
- `langchain-core==1.6.6`

## Spike Reuse Assessment

| Spike Code | Reuse in P1+ | Notes |
|---|---|---|
| `schemas.py` | Partial — refine with Pydantic models | Current dataclasses are spike-quality |
| `workflow.py` | Structure reusable — nodes need real logic | Fan-out/fan-in/gate pattern is validated |
| `fake_model.py` | Keep as test fixture | Useful for unit tests throughout project |
| `providers.py` | Reusable — add retry/usage tracking | Error classification pattern is solid |
| Test suite | Keep and extend | Core acceptance criteria tests |
