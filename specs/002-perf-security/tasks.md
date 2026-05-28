# Tasks: Performance & Security Hardening

## Phase 1: Setup

- [ ] T001 Create `investigator/lib/` package with `__init__.py`

---

## Phase 2: Foundational

- [ ] T002 Implement `RateLimiter` in `investigator/lib/rate_limiter.py`
- [ ] T003 Implement `ErrorSanitizer` in `investigator/lib/sanitizer.py`
- [ ] T004 Add `CatalogCache` with 60s TTL to `investigator/agent/coral_client.py`

---

## Phase 3: User Story 1 — Rate limiting & abuse prevention (P1)

**Goal**: Bot rejects excessive/malformed requests safely

- [ ] T005 [P] [US1] Test rate limiter in `investigator/tests/test_rate_limiter.py`
- [ ] T006 [P] [US1] Test `parse_flags()` sanitizes path-traversal in `investigator/tests/test_integration.py`
- [ ] T007 [P] [US1] Integrate `RateLimiter` into `investigator/bot/handler.py` — check before enqueue
- [ ] T008 [US1] Add input truncation (5000 chars) in `investigator/bot/handler.py:extract_question()`
- [ ] T009 [US1] Add `--service` path-traversal sanitization in `investigator/agent/core.py:_sanitize_service()`

---

## Phase 4: User Story 2 — Error message sanitization (P1)

**Goal**: No internal paths, env vars, or stack traces leak to Slack

- [ ] T010 [P] [US2] Test `ErrorSanitizer` in `investigator/tests/test_sanitizer.py`
- [ ] T011 [P] [US2] Integrate `ErrorSanitizer` into error formatting in `investigator/bot/handler.py`
- [ ] T012 [US2] Add env var redaction patterns to sanitizer
- [ ] T013 [US2] Add 500-char truncation to error detail blocks in `investigator/bot/formatter.py`

---

## Phase 5: User Story 3 — Query performance (P2)

**Goal**: Faster investigations through caching and result caps

- [ ] T014 [P] [US3] Test catalog cache TTL in `investigator/tests/test_coral_client.py`
- [ ] T015 [P] [US3] Reduce `max_per_source` from 100 to 20 in `investigator/agent/core.py:_build_evidence_chain()`
- [ ] T016 [US3] Integrate `CatalogCache` into `CoralClient.list_catalog()` and `CoralClient.describe_table()`
- [ ] T017 [US3] Add large result summarization for Phase 2 LLM context in `investigator/agent/reasoning.py:_phase1_context()`

---

## Phase 6: Polish

- [ ] T018 Run full test suite: `make test`
- [ ] T019 Update `AGENTS.md` with new security + perf capabilities
