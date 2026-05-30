# Tasks: Performance & Security Hardening

## Phase 1: Setup

- [x] T001 Create `investigator/lib/` package with `__init__.py`

---

## Phase 2: Foundational

- [x] T002 Implement `RateLimiter` in `investigator/lib/rate_limiter.py`
- [x] T003 Implement `ErrorSanitizer` in `investigator/lib/sanitizer.py`
- [x] T004 Add `CatalogCache` with 60s TTL to `investigator/agent/coral_client.py`

---

## Phase 3: User Story 1 — Rate limiting & abuse prevention (P1)

**Goal**: Bot rejects excessive/malformed requests safely

- [x] T005 [P] [US1] Test rate limiter in `investigator/tests/test_rate_limiter.py`
- [x] T006 [P] [US1] Test `parse_flags()` sanitizes path-traversal in `investigator/tests/test_integration.py`
- [x] T007 [P] [US1] Integrate `RateLimiter` into `investigator/bot/handler.py` — check before enqueue
- [x] T008 [US1] Add input truncation (5000 chars) in `investigator/bot/handler.py:extract_question()`
- [x] T009 [US1] Add `--service` path-traversal sanitization in `investigator/agent/core.py:_sanitize_service()`

---

## Phase 4: User Story 2 — Error message sanitization (P1)

**Goal**: No internal paths, env vars, or stack traces leak to Slack

- [x] T010 [P] [US2] Test `ErrorSanitizer` in `investigator/tests/test_sanitizer.py`
- [x] T011 [P] [US2] Integrate `ErrorSanitizer` into error formatting in `investigator/bot/handler.py`
- [x] T012 [US2] Add env var redaction patterns to sanitizer
- [x] T013 [US2] Add 500-char truncation to error detail blocks in `investigator/bot/formatter.py`

---

## Phase 5: User Story 3 — Query performance (P2)

**Goal**: Faster investigations through caching and result caps

- [x] T014 [P] [US3] Test catalog cache TTL in `investigator/tests/test_coral_client.py`
- [x] T015 [P] [US3] Reduce `max_per_source` from 100 to 20 in `investigator/agent/core.py:_build_evidence_chain()`
- [x] T016 [US3] Integrate `CatalogCache` into `CoralClient.list_catalog()` and `CoralClient.describe_table()`
- [x] T017 [US3] Add large result summarization for Phase 2 LLM context in `investigator/agent/reasoning.py:_phase1_context()`

---

## Phase 6: Polish

- [x] T018 Run full test suite: `make test`
- [x] T019 Update `AGENTS.md` with new security + perf capabilities
