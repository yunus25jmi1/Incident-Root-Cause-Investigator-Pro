# Implementation Plan: Error Resilience & Recovery

**Branch**: `001-error-resilience` | **Date**: 2026-05-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-error-resilience/spec.md`

## Summary

Add error resilience to the investigation pipeline: per-source failure isolation in Phase 1, retry + fallback for Phase 2 LLM-generated SQL errors, and persistent InvestigationQueue state for crash recovery.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: `asyncio`, `slack_bolt`, `openai>=1.0`, `coral` MCP stdio, `json`, `pathlib`

**Storage**: Local JSON files — `investigator/data/reports/` for reports, `investigator/data/queue_state.json` for queue persistence

**Testing**: `pytest` + `pytest-asyncio` + `pytest-cov`

**Target Platform**: Linux server (Ubuntu)

**Project Type**: CLI-based Slack agent (Socket Mode)

**Performance Goals**: Queue persistence writes < 100ms; Phase 1 per-source error isolation adds no latency to healthy sources

**Constraints**: Zero external storage (no Redis/DB); must work offline; must not break existing 234 tests

**Scale/Scope**: Single process, serial queue (max 10 items), 5 data sources

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Notes |
|-----------|-------|-------|
| I. AI-First Agent Loop | ✅ PASS | LLM-driven recovery (retry + fallback) aligns with AI-first philosophy |
| II. Data Source Abstraction | ✅ PASS | Error isolation respects Coral-only data access; no direct API calls added |
| III. Test-Driven Quality | ✅ PASS | All new code MUST have corresponding tests; 234-test baseline must not regress |
| IV. Mock-First Development | ✅ PASS | Error scenarios tested by manipulating mock sources (e.g., dropping JSONL file) |
| V. Security & Read-Only | ✅ PASS | No mutation operations; ReadOnlyValidator hardening only; no credential exposure |

## Project Structure

### Documentation (this feature)

```text
specs/001-error-resilience/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
investigator/
├── agent/
│   ├── coral_client.py     # + retry decorator, improved error classification
│   ├── core.py             # + per-source partial failure handling, source health tracking
│   └── reasoning.py        # + Phase 2 retry budget, fallback query logic
├── bot/
│   ├── handler.py          # + graceful startup queue restoration
│   ├── queue.py            # + disk persistence, crash recovery
│   └── formatter.py        # + source health section in report blocks
├── scripts/
│   └── seed_all.py         # (unchanged)
└── tests/
    ├── test_coral_client.py   # + retry & error classification tests
    ├── test_core.py           # + partial failure isolation tests
    ├── test_reasoning.py      # + Phase 2 retry budget tests
    ├── test_queue.py          # + persistence & crash recovery tests
    └── test_integration.py    # + scenario: source failure mid-investigation
```

**Structure Decision**: Single project — all changes are within existing module boundaries. No new top-level directories.

## Complexity Tracking

No constitution violations. All changes are additive within existing module patterns.

## Phase 0: Research

### Unknowns & Decisions

The spec has no `[NEEDS CLARIFICATION]` markers. All requirements are well-defined against the existing codebase.

### Design Decisions (pre-validated against codebase):

1. **Retry strategy**: Exponential backoff (1s, 2s, 4s) with jitter for transient Coral errors; no retry for `TABLE_NOT_FOUND` / `SOURCE_NOT_FOUND` (permanent)
2. **Queue persistence**: Append-only JSON log (`investigator/data/queue_state.jsonl`) — one JSON object per line for enqueue/dequeue events. Simplifies recovery with no locking overhead for a single-process serial queue
3. **Phase 2 fallback**: When LLM SQL fails, re-query the same source with a simple `SELECT * FROM table LIMIT 5` fallback instead of failing
4. **Source health tracking**: New dataclass `SourceHealth` with fields: `status` (ok/degraded/failed), `error_count`, `last_error`, `retry_count`. Reset on successful query

## Phase 1: Design & Contracts

### Data Model

See [data-model.md](data-model.md) for complete entity definitions.

### Contracts

No new external interfaces. Internal contracts:

1. **`AgentCore.investigate_with_reasoning()`** — returns report with `sources` dict now including `status: "ok" | "degraded" | "failed"` per source
2. **`InvestigationQueue.state`** property — returns serializable queue state for persistence
3. **`ReasoningEngine.analyze_with_loop()`** — accepts optional `retry_budget` parameter (default 2)

### Agent Context Update

See `AGENTS.md` — updated to reference this plan.

## Quickstart

See [quickstart.md](quickstart.md) for developer setup of error resilience testing.
