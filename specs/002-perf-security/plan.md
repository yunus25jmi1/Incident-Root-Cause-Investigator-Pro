# Implementation Plan: Performance & Security Hardening

**Branch**: `002-perf-security` | **Date**: 2026-05-28 | **Spec**: [spec.md](spec.md)

## Summary

Add rate limiting, error message sanitization, and query performance optimizations to the investigation pipeline.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: `asyncio`, `slack_bolt`, `time`, `re`

**Storage**: In-memory rate limiter dict; in-memory TTL cache for catalog

**Testing**: `pytest` with time mocking for rate limiter and cache TTL

**Target Platform**: Linux server (Ubuntu)

**Project Type**: CLI-based Slack agent (Socket Mode)

**Performance Goals**: Report gen <1s with 500+ rows/source; catalog cache hits <5ms

**Constraints**: Zero external storage for rate limiter (in-memory only, resets on restart)

**Scale/Scope**: Single process, serial queue, 5 data sources

## Constitution Check

| Principle | Check | Notes |
|-----------|-------|-------|
| I. AI-First Agent Loop | ✅ PASS | No changes to agent loop |
| II. Data Source Abstraction | ✅ PASS | Catalog cache still uses Coral MCP; no direct API calls |
| III. Test-Driven Quality | ✅ PASS | All new code MUST have tests |
| IV. Mock-First Development | ✅ PASS | Test with mock data |
| V. Security & Read-Only | ✅ PASS | Directly implements security principle — error sanitization + rate limiting |

## Project Structure

```
specs/002-perf-security/
├── plan.md
├── spec.md
├── tasks.md
└── checklists/requirements.md

investigator/
├── agent/
│   ├── coral_client.py     # + CatalogCache with TTL
│   └── core.py             # + evidence chain cap reduction (20 vs 100)
├── bot/
│   ├── handler.py          # + RateLimiter, input truncation, error sanitization
│   └── queue.py            # + rate-limited enqueue
├── lib/                    # NEW
│   ├── __init__.py
│   ├── rate_limiter.py     # Per-user sliding window rate limiter
│   └── sanitizer.py        # ErrorSanitizer utility
└── tests/
    ├── test_rate_limiter.py
    ├── test_sanitizer.py
    └── test_queue.py       # + rate limiting tests
```

## Phase 0: Research

All requirements are well-defined. Key design decisions:

1. **Rate limiter**: Sliding window via `collections.deque` of timestamps per user ID. O(1) append/popleft. Default window: 60s, limit: 10
2. **Error sanitizer**: Regex-based redaction for paths (`/[a-z]/...`), env var patterns (`SECRET|KEY|TOKEN|PASSWORD`), and generic truncation at 500 chars
3. **Catalog cache**: `dict` of `(table_name) -> (result, expiry_timestamp)`. `time.monotonic()` for TTL. Async-safe with `asyncio.Lock`
4. **Evidence chain cap**: Change `max_per_source` default from 100 to 20 in `_build_evidence_chain()`

## Phase 1: Design & Contracts

### New Modules

- `investigator/lib/rate_limiter.py` — `RateLimiter` class
- `investigator/lib/sanitizer.py` — `ErrorSanitizer` static methods

### Modified Modules

- `investigator/agent/coral_client.py` — `CoralClient` w/ catalog caching
- `investigator/agent/core.py` — Reduce `max_per_source` default to 20
- `investigator/bot/handler.py` — Rate limiting, truncation, error sanitization
- `investigator/bot/queue.py` — Rate check before enqueue

### Agent Context Update

Updated in `AGENTS.md`.
