# Feature Specification: Error Resilience & Recovery

**Feature Branch**: `001-error-resilience`

**Created**: 2026-05-28

**Status**: Draft

**Input**: User description: "Improve error resilience and recovery in the investigation pipeline"

## User Scenarios & Testing

### User Story 1 - Bot recovers gracefully from source failures (Priority: P1)

As an on-call engineer using the Slack agent, I want the investigation to complete even when one or more data sources fail temporarily, so that I still get a useful root-cause hypothesis instead of a cryptic error.

**Why this priority**: Source failures are the most common runtime error in a multi-source pipeline. Without this, a single source outage kills the entire investigation.

**Independent Test**: Can be fully tested by making one mock source unreachable and verifying the investigation still produces a report with partial evidence and clear source-failure annotations.

**Acceptance Scenarios**:

1. **Given** a configured Coral source is unreachable, **When** the user triggers an investigation, **Then** Phase 1 queries for other sources complete normally and the report includes a "source unavailable" note for the failed source
2. **Given** Phase 1 completes with partial failures, **When** the LLM requests follow-up Phase 2 SQL, **Then** queries to the failed source return a graceful error instead of crashing the loop
3. **Given** a transient failure (e.g., timeout), **When** the same source is re-queried in a subsequent Phase 2 turn, **Then** the query is retried and succeeds if the source recovers

---

### User Story 2 - LLM-generated SQL errors are handled with recovery (Priority: P2)

As a developer running the bot, I want the agent to recover gracefully when the LLM generates malformed SQL, so that the investigation doesn't halt on a single bad query.

**Why this priority**: Phase 2 depends entirely on LLM-generated SQL, which is inherently unreliable. Recovery here is critical for a self-healing agent.

**Independent Test**: Can be tested by injecting a deliberately bad SQL query into the Phase 2 loop and verifying the agent logs the error and continues with a fallback strategy.

**Acceptance Scenarios**:

1. **Given** the LLM generates a query that fails SQL validation (e.g., contains forbidden keywords), **When** the validator rejects it, **Then** the agent logs the violation, reports "query blocked" to the user, and continues the investigation
2. **Given** the LLM generates a syntactically valid but semantically wrong query (e.g., wrong table name), **When** Coral returns an error, **Then** the agent retries up to 2 times with a simplified fallback query before giving up
3. **Given** repeated query failures, **When** the retry budget is exhausted, **Then** the agent documents the failure in the evidence chain and proceeds to synthesis

---

### User Story 3 - Bot restarts safely without losing state (Priority: P3)

As a platform admin, I want the bot to survive restarts (deployment, crash, OOM) without corrupting the investigation queue, so that ongoing investigations are completed after recovery.

**Why this priority**: Less common but high impact when it happens — losing an in-progress investigation erodes user trust.

**Independent Test**: Can be tested by simulating a bot crash mid-investigation and verifying the queue persists to disk and resumes on restart.

**Acceptance Scenarios**:

1. **Given** an investigation is in progress, **When** the bot process is killed and restarted, **Then** pending investigations in the queue are restored from persistent storage
2. **Given** the bot restarts with an empty queue, **When** there are completed reports on disk, **Then** `/postmortem` commands still work against saved reports
3. **Given** a corrupt queue file on restart, **When** the bot initializes, **Then** it logs the corruption, starts with an empty queue, and does not crash

---

### Edge Cases

- What happens when ALL 5 sources fail simultaneously? — Report should say "No data available from any source" with error details
- How does the system handle repeated LLM timeouts (30s+) in Phase 2? — Agent should timeout after 3 consecutive failures and synthesize with Phase 1 data only
- What happens when the Slack API temporarily disconnects (Socket Mode reconnection)? — Bolt SDK handles reconnection; queue should survive the blip

## Requirements

### Functional Requirements

- **FR-001**: AgentCore MUST catch per-source query failures and collect partial results rather than aborting the entire investigation
- **FR-002**: The system MUST log each source failure with source name, error type, and timestamp to `investigator/data/reports/` for postmortem
- **FR-003**: The final report MUST include a "Source Health" section listing which sources succeeded, failed, or were unavailable
- **FR-004**: Phase 2 loop MUST have a configurable retry budget (default: 2 retries per failed query) before marking a source as degraded
- **FR-005**: ReadOnlyValidator violations MUST be logged with the offending SQL text (truncated to 200 chars) and the agent MUST NOT crash
- **FR-006**: InvestigationQueue MUST persist its state to disk on each enqueue/dequeue operation
- **FR-007**: On bot startup, InvestigationQueue MUST attempt to restore persisted state; on corruption, MUST log warning and start fresh
- **FR-008**: Phase 2 loop MUST have a configurable max consecutive failure threshold (default: 3) after which it exits to synthesis

### Key Entities

- **InvestigationReport**: Evidence chain with per-source status, error annotations, LLM inferences, and final hypothesis
- **SourceHealth**: Per-source record of success/failure, error count, last error timestamp, and retry count
- **QueueState**: Persisted JSON representing pending/deferred investigations with their creation timestamps

## Success Criteria

### Measurable Outcomes

- **SC-001**: A single source failure reduces report completeness but never crashes the agent — measured by injection test with 1 of 5 sources down
- **SC-002**: LLM-generated query errors are recovered from automatically in >= 80% of cases (retry + fallback) — measured by fuzz-testing the Phase 2 loop with deliberately bad SQL
- **SC-003**: Bot restart with persisted queue restores all pending investigations within 5 seconds — measured by integration test
- **SC-004**: "Source Health" section appears in all reports with partial failures — measured by automated check on report generation

## Assumptions

- Error recovery is best-effort — if all sources fail simultaneously, the agent reports the outage rather than inventing data
- Queue persistence is local to the bot process (no external storage like Redis or Postgres)
- The Slack Bolt SDK handles Socket Mode reconnection transparently; we should not reimplement it
- Retry budget of 2 is sufficient for transient failures; permanent failures (e.g., misconfigured source) are not retried indefinitely
