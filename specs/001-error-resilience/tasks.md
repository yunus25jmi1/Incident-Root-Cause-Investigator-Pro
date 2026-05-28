# Tasks: Error Resilience & Recovery

**Input**: Design documents from `specs/001-error-resilience/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Tests are included — this feature requires TDD approach per constitution principle III.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Python package at `investigator/`, tests at `investigator/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add shared error resilience types, helpers, and test infrastructure

- [ ] T001 Add `SourceStatus` enum and retry decorator to `investigator/agent/coral_client.py`
- [ ] T002 [P] Create `investigator/data/` directory with `.gitkeep` for queue state persistence
- [ ] T003 Add retry-with-backoff utility function in `investigator/agent/coral_client.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core error recovery infrastructure that MUST be complete before ANY user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Add `SourceHealth` tracking dataclass and per-source health dict management in `investigator/agent/core.py`
- [ ] T005 [P] Add `_retry_coral_query()` method with exponential backoff to `investigator/agent/coral_client.py`
- [ ] T006 Add error classification helper (`is_transient_error`) to `investigator/agent/coral_client.py`
- [ ] T007 [P] Add `QueuePersistence` class for JSONL-based queue state in `investigator/bot/queue.py`
- [ ] T008 Add `_fallback_select()` for generating simple `SELECT * FROM table LIMIT 5` queries in `investigator/agent/core.py`

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Per-source failure isolation (Priority: P1) 🎯 MVP

**Goal**: Investigation completes even when individual sources fail, with partial results and annotated source health

**Independent Test**: Corrupt one mock JSONL file, run investigation, verify report contains partial data with failed-source annotation

### Tests for User Story 1

- [ ] T009 [P] [US1] Test per-source error isolation in `investigator/tests/test_core.py` (corrupt sentry, verify other 4 sources return data)
- [ ] T010 [US1] Test source health tracking in report output in `investigator/tests/test_integration.py`

### Implementation for User Story 1

- [ ] T011 [P] [US1] Wrap each Phase 1 source query in try/except with `SourceHealth` tracking in `investigator/agent/core.py:_run_phase1()`
- [ ] T012 [P] [US1] Add `retry_count` and `fallback_used` fields to `SourceHealth` in `investigator/agent/core.py`
- [ ] T013 [US1] Update `_build_report()` to include per-source `status`, `retries`, and `fallback` in report output in `investigator/agent/core.py`
- [ ] T014 [US1] Add `_build_source_health_section()` for "Source Health" report block in `investigator/agent/core.py`
- [ ] T015 [US1] Expand `sources` status from `ok`/`empty` to `ok`/`degraded`/`failed` in `investigator/agent/core.py:_build_report()`

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 — LLM SQL error recovery (Priority: P2)

**Goal**: Phase 2 loop retries failed LLM-generated SQL with fallback queries instead of crashing

**Independent Test**: Inject deliberately bad SQL via mock LLM response, verify agent retries with fallback and continues loop

### Tests for User Story 2

- [ ] T016 [P] [US2] Test Phase 2 retry budget exhaustion in `investigator/tests/test_reasoning.py`
- [ ] T017 [US2] Test fallback query generation for INVALID_SQL errors in `investigator/tests/test_core.py`
- [ ] T018 [US2] Test consecutive failure threshold exits loop to synthesis in `investigator/tests/test_reasoning.py`

### Implementation for User Story 2

- [ ] T019 [P] [US2] Add `retry_budget` parameter to `analyze_with_loop()` in `investigator/agent/reasoning.py`
- [ ] T020 [P] [US2] Add `max_consecutive_failures` parameter (default 3) in `investigator/agent/reasoning.py`
- [ ] T021 [US2] Implement retry loop for failed Phase 2 SQL queries in `investigator/agent/reasoning.py:analyze_with_loop()`
- [ ] T022 [US2] Call `_fallback_select()` when retry budget exhausted but fallback is possible in `investigator/agent/core.py`
- [ ] T023 [US2] Track `phase2_health` counters in report output in `investigator/agent/core.py:_merge_llm_into_report()`
- [ ] T024 [US2] Log ReadOnlyValidator violations with truncated SQL in `investigator/agent/coral_client.py:ReadOnlyValidator`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 — Crash recovery & queue persistence (Priority: P3)

**Goal**: InvestigationQueue persists state to disk and survives bot restarts

**Independent Test**: Enqueue an investigation, kill the process, restart, verify pending investigation resumes

### Tests for User Story 3

- [ ] T025 [P] [US3] Test queue state save/load round-trip in `investigator/tests/test_queue.py`
- [ ] T026 [US3] Test corrupt queue state on startup logs warning and starts fresh in `investigator/tests/test_queue.py`
- [ ] T027 [US3] Test `/postmortem` works after restart with saved reports in `investigator/tests/test_e2e.py`

### Implementation for User Story 3

- [ ] T028 [P] [US3] Implement `_save_state()` method on `InvestigationQueue` in `investigator/bot/queue.py`
- [ ] T029 [P] [US3] Implement `_load_state()` classmethod on `InvestigationQueue` in `investigator/bot/queue.py`
- [ ] T030 [US3] Call `_save_state()` on each enqueue/dequeue in `investigator/bot/queue.py`
- [ ] T031 [US3] Add queue state restoration in `handler.py:main()` on bot startup in `investigator/bot/handler.py`
- [ ] T032 [US3] Add `replay_queue` logic after restore in `investigator/bot/handler.py`

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T033 Update `investigator/agent/reasoning.py` SYSTEM_PROMPT to document retry behavior
- [ ] T034 [P] Run full test suite: `make test` — verify 234+ baseline + new tests pass
- [ ] T035 [P] Update `AGENTS.md` to reference new error resilience capabilities
- [ ] T036 Run `seed_all.py --activate` to refresh mock data after testing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — correlates data; no cross-story deps
- **US2 (Phase 4)**: Depends on Phase 2 — modifies Phase 2 loop; independent of US1
- **US3 (Phase 5)**: Depends on Phase 2 — queue infra; independent of US1/US2
- **Polish (Phase 6)**: Depends on all phases complete

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories — **MVP scope**
- **User Story 2 (P2)**: No dependencies on other stories
- **User Story 3 (P3)**: No dependencies on other stories

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Foundation types before consumer code
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- T001, T002 run in parallel
- T005, T007, T008 run in parallel
- All model/base-type tasks within a phase (marked [P]) run in parallel
- All user stories can be implemented in parallel after Phase 2 completes

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 — per-source failure isolation
4. **STOP and VALIDATE**: Test US1 independently
5. Proceed to US2 or US3

### Incremental Delivery

1. Setup + Foundational → Core resilience infra ready
2. Add US1 → partial failure tolerance (MVP!)
3. Add US2 → LLM SQL recovery
4. Add US3 → crash recovery
