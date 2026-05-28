# Data Model: Error Resilience & Recovery

## SourceHealth

Per-source health tracker for a single investigation.

| Field | Type | Description |
|-------|------|-------------|
| `source_name` | `str` | Logical source key (e.g., `sentry_issues`) |
| `status` | `SourceStatus` | `ok` / `degraded` / `failed` |
| `error_count` | `int` | Cumulative errors in this investigation |
| `last_error` | `str \| None` | Last error message (truncated 500 chars) |
| `last_error_code` | `str \| None` | CoralError code string |
| `retry_count` | `int` | Retries attempted |
| `fallback_used` | `bool` | Whether fallback query was used |

### States

```
INITIAL → ok (first query succeeds)
INITIAL → degraded (first query fails, fallback succeeds)
INITIAL → failed (first query fails, no fallback)
degraded → ok (subsequent query succeeds)
degraded → failed (retry budget exhausted)
```

## QueueEntry

Persisted queue item for crash recovery.

| Field | Type | Description |
|-------|------|-------------|
| `question` | `str` | User's investigation question |
| `channel` | `str` | Slack channel ID |
| `thread_ts` | `str` | Thread timestamp |
| `since` | `str` | --since flag value |
| `service` | `str` | --service flag value |
| `created_at` | `str` | ISO 8601 timestamp |
| `status` | `str` | `pending` / `processing` / `done` |

## Report Extension

Additional fields added to investigation report dict:

```python
{
    # ... existing fields ...
    "sources": {
        "sentry": {
            "status": "ok" | "degraded" | "failed",  # new field
            "count": int,
            "error": str | None,
            "error_code": str | None,
            "retries": int,                           # new field
            "fallback": bool,                          # new field
        },
        # ... same for datadog, github, pagerduty, slack
    },
    "phase2_health": {      # new section
        "total_queries": int,
        "failed_queries": int,
        "retries_used": int,
        "fallbacks_used": int,
    },
}
```
