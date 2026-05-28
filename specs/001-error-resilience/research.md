# Phase 0 Research: Error Resilience & Recovery

## Decision Log

### D1: Retry Strategy for Coral Transient Failures
- **Decision**: Exponential backoff (1s, 2s, 4s) with ±50% jitter; max 3 retries
- **Rationale**: Coral MCP stdio is a local subprocess — transient failures are typically timeout or race-condition. Short backoff is appropriate. Jitter prevents thundering herd on reconnection.
- **Alternatives considered**: Fixed 1s retry (too aggressive for sustained failures), no retry (customer sees degraded UX)

### D2: Queue Persistence Format
- **Decision**: Append-only JSONL file at `investigator/data/queue_state.jsonl`
- **Rationale**: Single-process serial queue needs no locking. JSONL (one JSON object per line) allows append without reading entire file. Crash recovery replays the log to reconstruct state.
- **Alternatives considered**: SQLite (overkill for a queue of max 10 items), pickle (fragile across Python versions), Redis (external dependency — violates zero-external-storage constraint)

### D3: Phase 2 Fallback Query Strategy
- **Decision**: When LLM-generated SQL fails validation or execution, retry with a simple `SELECT * FROM <table> LIMIT 5` for the intended source
- **Rationale**: LLM often generates wrong table names or syntax. A fallback to a known-good simple query recovers most cases. The LLM can still work with partial data.
- **Alternatives considered**: Silently skip the failed query (loses data), crash the loop (bad UX), re-prompt LLM (expensive, may repeat same error)

### D4: Source Health Tracking
- **Decision**: In-memory `SourceHealth` dict per source, reset at start of each investigation
- **Rationale**: Health is per-investigation — a source that failed in one investigation may succeed in the next. No need for cross-investigation health tracking in v1.
- **Alternatives considered**: Global health counters (adds complexity, unclear benefit for serial queue), persistent health DB (overkill)

## Error Classification Matrix

| Error Type | CoralError Code | Retry? | Fallback? |
|------------|----------------|--------|-----------|
| Connection failed | CONNECTION_FAILED | Yes (3x backoff) | No — skip source |
| Timeout | TIMEOUT | Yes (3x backoff) | No — skip source |
| Table not found | TABLE_NOT_FOUND | No | No — skip source |
| Source not found | SOURCE_NOT_FOUND | No | No — skip source |
| Malformed response | MALFORMED_RESPONSE | Yes (1x) | Yes — simple SELECT |
| Invalid SQL (LLM) | INVALID_SQL | No (don't retry bad SQL) | Yes — simple SELECT |
| Write operation | INVALID_SQL (ReadOnly) | No | No — log violation |
| Unknown | UNKNOWN | Yes (2x) | Yes — simple SELECT |
