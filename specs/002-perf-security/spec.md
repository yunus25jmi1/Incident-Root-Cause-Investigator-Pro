# Feature Specification: Performance & Security Hardening

**Feature Branch**: `002-perf-security`

**Created**: 2026-05-28

**Status**: Draft

**Input**: User description: "Improve performance and security standards across the investigation pipeline"

## User Scenarios & Testing

### User Story 1 - Rate limiting & abuse prevention (Priority: P1)

As a platform admin, I want the bot to reject excessive or malformed requests so that a single user cannot flood the queue or trigger internal errors.

**Why this priority**: Directly impacts availability and safety. No auth gate exists today.

**Independent Test**: Test that sending 20 rapid `@investigator` mentions within 1 second results in only `DEFAULT_MAX_QUEUE_SIZE` (10) being enqueued and the rest rejected with "rate limited".

**Acceptance Scenarios**:

1. **Given** a user sends more than 10 requests within a sliding 60s window, **When** the bot processes them, **Then** requests beyond the limit receive a "rate limited" response
2. **Given** a request contains path-traversal characters in `--service` flag, **When** parsed, **Then** the service name is sanitized and logged as a potential injection attempt
3. **Given** a request contains excessively long text (>5000 chars), **When** parsed, **Then** it is truncated before processing

---

### User Story 2 - Error message sanitization (Priority: P1)

As a security reviewer, I want error messages sent to Slack to never leak internal paths, environment variables, or stack traces, so that sensitive system details stay contained.

**Why this priority**: The constitution principle V (Security & Read-Only) requires this. Currently raw Coral errors could leak paths.

**Independent Test**: Inject an error with `"/home/user/.env"` in the message; verify the Slack output redacts or truncates the path.

**Acceptance Scenarios**:

1. **Given** a CoralError contains a file path (e.g., `/home/user/.env`), **When** the bot formats the error for Slack, **Then** the path is stripped or replaced with `[internal]`
2. **Given** an exception message exceeds 500 chars, **When** displayed in Slack, **Then** it is truncated with `… (truncated)`
3. **Given** an error contains `CORAL_API_KEY` or other known env var names, **When** formatted, **Then** the value is redacted to `[REDACTED]`

---

### User Story 3 - Query performance (Priority: P2)

As an on-call engineer, I want investigations to complete faster so that I get root-cause insights sooner during an incident.

**Why this priority**: User Story 1 from the original spec (per-source failure) is already done. This is the next UX bottleneck.

**Independent Test**: Return 1000+ mock rows from a single source; verify evidence chain truncation and report generation stay under 500ms.

**Acceptance Scenarios**:

1. **Given** a source returns 500+ rows in Phase 1, **When** the report is built, **Then** the evidence chain caps at 20 items per source (down from 100) to keep Slack messages responsive
2. **Given** `list_tables` / `describe_table` is called, **When** the catalog hasn't changed, **Then** results are cached for 60s to avoid redundant Coral MCP calls
3. **Given** large result sets (>1000 rows), **When** passed to the LLM in Phase 2 context, **Then** the context is summarized (counts + top 5 rows only) rather than serialized in full

---

### Edge Cases

- What happens when `/postmortem` is called with an incident ID containing shell metacharacters? — Sanitized by `_sanitize_id`
- What happens when LLM response exceeds `max_tokens`? — Already handled by truncation, but no alert is raised; add warning log
- What happens when the same user spams the same question? — Rate limiter should treat all requests equally, no per-question dedup in v1

## Requirements

### Functional Requirements

- **FR-001**: `InvestigationQueue` MUST enforce a per-user rate limit (max N requests per sliding 60s window, configurable via `RATE_LIMIT_PER_WINDOW` env var, default 10)
- **FR-002**: `parse_flags()` MUST sanitize `--service` values against path-traversal patterns (`../`, `~`, absolute paths)
- **FR-003**: `handler.py` MUST truncate incoming question text to 5000 characters before processing
- **FR-004**: `handler.py` error responses MUST pass through `_sanitize_mrkdwn()` and additionally redact: absolute paths (`/home/...`, `/tmp/...`), env var names (`SECRET`, `KEY`, `TOKEN`, `PASSWORD`)
- **FR-005**: `formatter.py` MUST limit error message detail blocks to 500 characters with truncation indicator
- **FR-006**: `_build_evidence_chain()` MUST reduce `max_per_source` default from 100 to 20
- **FR-007**: `CoralClient` MUST cache `list_tables` and `describe_table` results in-memory with 60s TTL
- **FR-008**: Phase 2 LLM context MUST summarize large result sets (>100 rows) instead of passing full JSON

### Key Entities

- **RateLimiter**: Tracks request timestamps per user ID; exposes `is_rate_limited(user_id)` method
- **ErrorSanitizer**: Static utility that redacts paths, env var values, and truncates long messages
- **CatalogCache**: In-memory TTL cache for `(table_name) -> (result, expiry)` entries

## Success Criteria

### Measurable Outcomes

- **SC-001**: Rate limiter allows at most 10 requests per 60s per user — measured by integration test
- **SC-002**: Zero file paths or env vars appear in Slack-formatted error messages — measured by injection test suite
- **SC-003**: Report generation with 500+ rows per source completes in under 1 second — measured by performance test
- **SC-004**: Catalog lookups after first call are served from cache and complete in <5ms — measured by unit test

## Assumptions

- Rate limiting is per-user (Slack user ID), not per-channel
- Cache TTL of 60s is acceptable for catalog staleness (sources rarely change mid-investigation)
- Truncation to 5000 chars is safe; legitimate questions are rarely longer
- The existing `_sanitize_id()` function handles incident ID sanitization; no changes needed there
