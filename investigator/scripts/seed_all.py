"""
Single realistic incident — CDN Cache Key config drift.
Inspired by Cloudflare 2022-06-21 Tiered Cache outage + Fastly 2021-06-08 global 502 outage.

Story:
  PR #4381 ("Optimize cache key for tiered distribution") is deployed to staging, promoted to prod.
  The change skips cache-key normalization for authenticated requests, causing every request to
  miss cache and hit the origin. Origin pool is overwhelmed → 502s globally.
  On-call detects via Sentry spike → Datadog alert → PagerDuty page.
  Revert PR #4382 is merged, cache purged. Incident resolved in 47 minutes.
  Postmortem identifies missing code review and missing canary deployment.

Sources: sentry, datadog, github, pagerduty, slack
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sources", "mocks")
)

# Incident timeline reference:
# 2026-05-27 02:00 UTC — PR #4381 deployed to prod
# 02:02 — Sentry detects CacheKeyMismatchError spike (1462/min)
# 02:03 — Datadog auto-creates incident SEV-1
# 02:04 — PagerDuty INC-804 triggers high-urgency
# 02:04:30 — Slack #incidents lights up
# 02:05 — Charlie (on-call) acknowledges
# 02:06 — Revert PR #4382 merged
# 02:10 — Cache purge begins
# 02:47 — Error rate returns to baseline
# 02:48 — INC-804 resolved
# 03:00 — Postmortem Slack thread starts

INCIDENT_EPOCH = datetime.now(timezone.utc) - timedelta(hours=3)


def dt(hours: float) -> str:
    return (INCIDENT_EPOCH + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def dt_min(mins: float) -> str:
    return dt(mins / 60.0)


# ── Sentry Issues ────────────────────────────────────────────────────
SENTRY_ISSUES = [
    dict(id="SENT-001", short_id="CDN-1A",
         title="CacheKeyMismatchError: Origin returned 502 for cache key '//checkout/v1/'",
         status="unresolved", level="error", count=1462, user_count=8900,
         first_seen=dt_min(2), last_seen=dt_min(47), project="cdn-edge",
         query="CacheKeyMismatchError"),
    dict(id="SENT-002", short_id="CDN-2B",
         title="Http502Error: upstream connect error or disconnect/reset before headers",
         status="unresolved", level="fatal", count=8400, user_count=32000,
         first_seen=dt_min(2), last_seen=dt_min(47), project="api-gateway",
         query="Http502Error upstream connect"),
    dict(id="SENT-003", short_id="CDN-3C",
         title="OriginConnectionTimeout: origin pool at 100% capacity, request queued 31s",
         status="unresolved", level="error", count=3200, user_count=15000,
         first_seen=dt_min(3), last_seen=dt_min(46), project="cdn-origin",
         query="OriginConnectionTimeout pool capacity"),
    dict(id="SENT-004", short_id="CDN-4D",
         title="CacheMissRatioExceeded: 99.7% of requests bypassing cache (threshold: 5%)",
         status="unresolved", level="error", count=1, user_count=0,
         first_seen=dt_min(4), last_seen=dt_min(45), project="cdn-edge",
         query="CacheMissRatioExceeded"),
    dict(id="SENT-005", short_id="CDN-5E",
         title="OriginPoolExhaustion: all 128 connections in pool 'us-east-1a' in use",
         status="unresolved", level="fatal", count=5600, user_count=22000,
         first_seen=dt_min(4), last_seen=dt_min(45), project="cdn-origin",
         query="OriginPoolExhaustion"),
    dict(id="SENT-006", short_id="CDN-6F",
         title="Warning: Cache hit ratio dropped from 92% to 0.3% on /api/checkout endpoint",
         status="unresolved", level="warning", count=1, user_count=0,
         first_seen=dt_min(5), last_seen=dt_min(44), project="cdn-edge",
         query="Cache hit ratio"),
    dict(id="SENT-007", short_id="CDN-7G",
         title="TimeoutError: checkout-service upstream timed out (30s) on cache-miss requests",
         status="unresolved", level="error", count=2100, user_count=9800,
         first_seen=dt_min(5), last_seen=dt_min(45), project="checkout-service",
         query="TimeoutError checkout upstream"),
    dict(id="SENT-008", short_id="CDN-8H",
         title="CircuitBreakerOpen: payment-service circuit breaker opened at 78% failure rate",
         status="unresolved", level="error", count=3400, user_count=16000,
         first_seen=dt_min(6), last_seen=dt_min(44), project="payment-service",
         query="CircuitBreakerOpen payment"),
    dict(id="SENT-009", short_id="CDN-9I",
         title="Warning: Backpressure signal from origin pool, 3400 requests dropped",
         status="unresolved", level="warning", count=1, user_count=0,
         first_seen=dt_min(6), last_seen=dt_min(43), project="cdn-origin",
         query="Backpressure origin pool"),
    dict(id="SENT-010", short_id="CDN-10J",
         title="CachePurgeComplete: full cache purge initiated by on-call [Charlie]",
         status="resolved", level="info", count=1, user_count=1,
         first_seen=dt_min(10), last_seen=dt_min(10), project="cdn-edge",
         query="CachePurgeComplete"),
    dict(id="SENT-011", short_id="CDN-11K",
         title="ErrorRateNormalized: 502 rate returned to baseline (0.12%) at 02:47 UTC",
         status="resolved", level="info", count=1, user_count=0,
         first_seen=dt_min(47), last_seen=dt_min(47), project="cdn-edge",
         query="ErrorRateNormalized"),
    dict(id="SENT-012", short_id="CDN-12L",
         title="SlowQueryWarning: SELECT on cache_entries table took 45s during incident",
         status="unresolved", level="warning", count=23, user_count=5,
         first_seen=dt_min(8), last_seen=dt_min(46), project="cdn-edge",
         query="SlowQueryWarning cache_entries"),
    dict(id="SENT-013", short_id="CDN-13M",
         title="ValidationError: missing 'x-cache-key' header in 78% of requests at edge",
         status="unresolved", level="error", count=7800, user_count=29000,
         first_seen=dt_min(2), last_seen=dt_min(47), project="cdn-edge",
         query="ValidationError x-cache-key"),
    dict(id="SENT-014", short_id="CDN-14N",
         title="MemoryWarning: edge node heap usage 97% due to uncached request surge",
         status="unresolved", level="warning", count=45, user_count=0,
         first_seen=dt_min(10), last_seen=dt_min(45), project="cdn-edge",
         query="MemoryWarning edge heap"),
    dict(id="SENT-015", short_id="CDN-15O",
         title="ConfigDeployDetected: tiered-cache config v2.1.8 rolled out to 100% of POPs",
         status="resolved", level="info", count=1, user_count=1,
         first_seen=dt(0), last_seen=dt(0), project="deploy-service",
         query="ConfigDeployDetected tiered-cache"),
]

# ── Datadog Incidents ────────────────────────────────────────────────
DATADOG_INCIDENTS = [
    dict(id="dd-inc-001", title="[AUTO] CDN error rate > 5% — 502 spike on all POPs",
         status="active", severity="SEV-1",
         created=dt_min(3), modified=dt_min(48), resolved_at=dt_min(48),
         customer_impacted=True),
    dict(id="dd-inc-002", title="Cache hit ratio collapse: 92% → 0.3% on /api/checkout",
         status="active", severity="SEV-2",
         created=dt_min(3), modified=dt_min(47), resolved_at=dt_min(47),
         customer_impacted=True),
    dict(id="dd-inc-003", title="Origin pool 'us-east-1a' at 100% connection utilization",
         status="active", severity="SEV-1",
         created=dt_min(4), modified=dt_min(46), resolved_at=dt_min(46),
         customer_impacted=True),
    dict(id="dd-inc-004", title="checkout-service p99 latency 30s (baseline: 120ms)",
         status="active", severity="SEV-2",
         created=dt_min(5), modified=dt_min(45), resolved_at=dt_min(45),
         customer_impacted=True),
    dict(id="dd-inc-005", title="payment-service circuit breaker opened at 78% failure",
         status="active", severity="SEV-2",
         created=dt_min(6), modified=dt_min(44), resolved_at=dt_min(44),
         customer_impacted=True),
    dict(id="dd-inc-006", title="Global traffic drop: request volume down 62% (users hitting 502)",
         status="active", severity="SEV-1",
         created=dt_min(5), modified=dt_min(48), resolved_at=dt_min(48),
         customer_impacted=True),
    dict(id="dd-inc-007", title="Edge node CPU 97% across all POPs (us-east, eu-west, ap-south)",
         status="active", severity="SEV-3",
         created=dt_min(10), modified=dt_min(45), resolved_at=dt_min(45),
         customer_impacted=True),
    dict(id="dd-inc-008", title="[RESOLVED] Full cache purge completed — error rate recovering",
         status="resolved", severity="SEV-4",
         created=dt_min(11), modified=dt_min(47), resolved_at=dt_min(47),
         customer_impacted=False),
]

# ── GitHub Pulls ─────────────────────────────────────────────────────
GITHUB_PULLS = [
    dict(number=4381, title="feat: optimize cache key for tiered distribution",
         state="merged", merged=True, draft=False,
         body="""Normalizes cache keys for authenticated vs anonymous requests.
Cache key now includes 'x-cache-key' header when present.
Deployed to 100% of edge POPs via progressive rollout.

⚠ Root cause of INC-804""",
         user__login="Alice", user="Alice",
         base__ref="main", head__label="feat/tiered-cache-key",
         created_at=dt(-48), merged_at=dt(0), closed_at=dt(0), updated_at=dt(0),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4381",
         additions=87, deletions=12, changed_files=4, comments=3, commits=2,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
    dict(number=4382, title='revert: "feat: optimize cache key for tiered distribution"',
         state="merged", merged=True, draft=False,
         body="Immediately reverts PR #4381. Cache key normalization had a bug where "
              "authenticated requests bypassed the cache entirely, causing origin overload.",
         user__login="Charlie", user="Charlie",
         base__ref="main", head__label="revert/tiered-cache-key",
         created_at=dt_min(5), merged_at=dt_min(6), closed_at=dt_min(6), updated_at=dt_min(6),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4382",
         additions=12, deletions=87, changed_files=4, comments=5, commits=1,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
    dict(number=4380, title="feat: add distributed tracing headers to cdn-edge",
         state="merged", merged=True, draft=False,
         body="Adds X-Request-ID and X-Trace-ID to all edge responses for debugging",
         user__login="Bob", user="Bob",
         base__ref="main", head__label="feat/tracing-headers",
         created_at=dt(-72), merged_at=dt(-60), closed_at=dt(-60), updated_at=dt(-60),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4380",
         additions=120, deletions=20, changed_files=8, comments=6, commits=3,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
    dict(number=4379, title="fix: handle SSL cert rotation for cdn-origin pool",
         state="merged", merged=True, draft=False,
         body="Updates CA bundle and adds cert expiry monitoring to origin health checks",
         user__login="Diana", user="Diana",
         base__ref="main", head__label="fix/ssl-origin-rotation",
         created_at=dt(-96), merged_at=dt(-84), closed_at=dt(-84), updated_at=dt(-84),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4379",
         additions=45, deletions=8, changed_files=3, comments=4, commits=2,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
    dict(number=4383, title="fix: add canary deployment step for cache config changes",
         state="open", merged=False, draft=False,
         body="Prevents future incidents by requiring a 5-minute canary window for all "
              "CDN config changes. Postmortem action item from INC-804.",
         user__login="Alice", user="Alice",
         base__ref="main", head__label="fix/canary-deploy",
         created_at=dt_min(120), merged_at=None, closed_at=None, updated_at=dt_min(60),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4383",
         additions=55, deletions=10, changed_files=3, comments=8, commits=3,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
    dict(number=4384, title="feat: add automated cache-hit-ratio canary check to deploy pipeline",
         state="open", merged=False, draft=False,
         body="Checks that cache hit ratio doesn't drop below 50% within 2 minutes of deploy. "
              "If it does, auto-rollback. Postmortem action item from INC-804.",
         user__login="Charlie", user="Charlie",
         base__ref="main", head__label="feat/cache-ratio-canary",
         created_at=dt_min(130), merged_at=None, closed_at=None, updated_at=dt_min(65),
         html_url="https://github.com/acme-corp/cdn-infra/pull/4384",
         additions=120, deletions=5, changed_files=6, comments=3, commits=4,
         mergeable_state="clean",
         owner="acme-corp", repo="cdn-infra"),
]

# ── PagerDuty Incidents ──────────────────────────────────────────────
PD_INCIDENTS = [
    dict(id="INC-804", title="CRITICAL: CDN 502 error storm — all POPs affected",
         status="triggered", urgency="high",
         created_at=dt_min(4), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-804-ack", title="CRITICAL: CDN 502 error storm — all POPs affected",
         status="acknowledged", urgency="high",
         created_at=dt_min(5), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-804-resolved", title="CRITICAL: CDN 502 error storm — all POPs affected",
         status="resolved", urgency="high",
         created_at=dt_min(48), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-805", title="Origin pool connection exhaustion — checkout-service",
         status="triggered", urgency="high",
         created_at=dt_min(4), escalation_level=1,
         escalation_policy_id="EP-ORIGIN"),
    dict(id="INC-805-resolved", title="Origin pool connection exhaustion — checkout-service",
         status="resolved", urgency="high",
         created_at=dt_min(46), escalation_level=1,
         escalation_policy_id="EP-ORIGIN"),
    dict(id="INC-806", title="Cache hit ratio anomaly: 92% → 0.3%",
         status="triggered", urgency="medium",
         created_at=dt_min(5), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-806-resolved", title="Cache hit ratio anomaly: 92% → 0.3%",
         status="resolved", urgency="medium",
         created_at=dt_min(47), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-801", title="SSL certificate expiry on api-gateway",
         status="resolved", urgency="medium",
         created_at=dt(-168), escalation_level=1,
         escalation_policy_id="EP-ORIGIN"),
    dict(id="INC-802", title="Docker registry pull rate limit on cdn-deploy",
         status="resolved", urgency="low",
         created_at=dt(-336), escalation_level=1,
         escalation_policy_id="EP-CDN"),
    dict(id="INC-803", title="Elasticsearch cluster yellow status on cdn-logs",
         status="resolved", urgency="low",
         created_at=dt(-72), escalation_level=1,
         escalation_policy_id="EP-CDN"),
]

PD_ONCALLS = [
    dict(id="oncall-cdn-1", escalation_policy_id="EP-CDN", escalation_level=1,
         name="Charlie", email="charlie@acme-corp.com"),
    dict(id="oncall-cdn-2", escalation_policy_id="EP-CDN", escalation_level=2,
         name="Diana Chen", email="diana@acme-corp.com"),
    dict(id="oncall-origin-1", escalation_policy_id="EP-ORIGIN", escalation_level=1,
         name="Alice", email="alice@acme-corp.com"),
    dict(id="oncall-origin-2", escalation_policy_id="EP-ORIGIN", escalation_level=2,
         name="Bob Smith", email="bob@acme-corp.com"),
]

# ── Slack Messages ───────────────────────────────────────────────────
SLACK_MESSAGES = [
    # Incident breakout — 02:04 UTC
    dict(user_id="U01CDN", text="<!channel> :red_circle: CDN 502 error rate just spiked to 8.4%. "
                                "PagerDuty INC-804 triggered. Check CDN-ALERTS channel.",
         ts=dt_min(4), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p1",
         reply_count=12, thread_ts=None, subtype="bot_message"),

    dict(user_id="U02CHARLIE", text="<@U02CHARLIE> you're on-call for CDN. INC-804 is high urgency.",
         ts=dt_min(4.5), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p2",
         reply_count=0, thread_ts=None, subtype="bot_message"),

    dict(user_id="U02CHARLIE", text="Acknowledging INC-804. Looking at Sentry now.",
         ts=dt_min(5), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p3",
         reply_count=3, thread_ts=None, subtype=None),

    dict(user_id="U02CHARLIE", text="Sentinel shows CacheKeyMismatchError on all POPs. "
                                    "Cache hit ratio dropped from 92% to 0.3%. Checking recent deploys.",
         ts=dt_min(5.5), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p4",
         reply_count=0, thread_ts=None, subtype=None),

    # Root cause found — 02:06 UTC
    dict(user_id="U03ALICE", text="PR #4381 was deployed at 02:00 UTC. Cache key normalization for tiered distribution.",
         ts=dt_min(6), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p5",
         reply_count=5, thread_ts=None, subtype=None),

    dict(user_id="U02CHARLIE", text="That's it. The cache key change skips normalization for authenticated requests. "
                                    "They're all bypassing cache and hitting origin. Opening revert now.",
         ts=dt_min(6.5), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p6",
         reply_count=0, thread_ts=None, subtype=None),

    dict(user_id="U03ALICE", text="Revert PR #4382 is up. Need two approvals. <@U02CHARLIE> <@U05DIANA>",
         ts=dt_min(6.8), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p7",
         reply_count=0, thread_ts=None, subtype=None),

    dict(user_id="U02CHARLIE", text="Approved and merged. Cache purge starting now.",
         ts=dt_min(7), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p8",
         reply_count=2, thread_ts=None, subtype=None),

    dict(user_id="U05DIANA", text="Cache purge initiated on all POPs. ETA ~30s for invalidation.",
         ts=dt_min(10), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p9",
         reply_count=0, thread_ts=None, subtype=None),

    # Recovery — 02:47 UTC
    dict(user_id="U02CHARLIE", text="Error rate dropping. Now at 2.1% and falling. Cache hit ratio recovering: 67%.",
         ts=dt_min(30), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p10",
         reply_count=0, thread_ts=None, subtype=None),

    dict(user_id="U02CHARLIE", text="Error rate back to baseline (0.12%). Resolving INC-804 and INC-805.",
         ts=dt_min(47), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p11",
         reply_count=8, thread_ts=None, subtype=None),

    dict(user_id="U01CDN", text=":large_green_circle: CDN 502 error rate normalized. "
                                "Total impact: 47 minutes. ~32k users affected. "
                                "Postmortem scheduled tomorrow 10am.",
         ts=dt_min(48), channel="C0INCIDENTS",
         permalink="https://acme-corp.slack.com/archives/C0INCIDENTS/p12",
         reply_count=0, thread_ts=None, subtype="bot_message"),

    # Postmortem planning — 03:00 UTC
    dict(user_id="U02CHARLIE", text="Root cause: PR #4381 introduced a cache key normalization bug. "
                                    "Authenticated requests were not normalized → always missed cache → "
                                    "origin pool overwhelmed → 502 errors cascade.\n\n"
                                    "Key issues: 1) No canary deployment for config changes 2) No automated "
                                    "cache hit ratio check 3) Review missed the edge case.\n\n"
                                    "Postmortem action items drafted as PR #4383 and #4384.",
         ts=dt_min(60), channel="C0POSTMORTEMS",
         permalink="https://acme-corp.slack.com/archives/C0POSTMORTEMS/p1",
         reply_count=0, thread_ts=None, subtype=None),

    dict(user_id="U03ALICE", text="Agreed on all points. I'll own the canary deployment PR. "
                                   "The cache key logic needs better test coverage too.",
         ts=dt_min(62), channel="C0POSTMORTEMS",
         permalink="https://acme-corp.slack.com/archives/C0POSTMORTEMS/p2",
         reply_count=3, thread_ts=None, subtype=None),

    dict(user_id="U05DIANA", text="Adding monitoring: we need a dashboard for cache hit ratio per-POP "
                                   "with PagerDuty integration under 50%.",
         ts=dt_min(65), channel="C0POSTMORTEMS",
         permalink="https://acme-corp.slack.com/archives/C0POSTMORTEMS/p3",
         reply_count=0, thread_ts=None, subtype=None),

    dict(user_id="U04BOB", text="Great analysis. Let's also add an automated rollback trigger when "
                                 "502 rate exceeds 2% within 3 minutes of any CDN deploy.",
         ts=dt_min(70), channel="C0POSTMORTEMS",
         permalink="https://acme-corp.slack.com/archives/C0POSTMORTEMS/p4",
         reply_count=2, thread_ts=None, subtype=None),
]

# ── Source YAML manifests ─────────────────────────────────────────────
SENTRY_COLS = [
    {"name": "id", "type": "Utf8", "nullable": False},
    {"name": "short_id", "type": "Utf8"},
    {"name": "title", "type": "Utf8"},
    {"name": "status", "type": "Utf8"},
    {"name": "level", "type": "Utf8"},
    {"name": "count", "type": "Int64"},
    {"name": "user_count", "type": "Int64"},
    {"name": "first_seen", "type": "Utf8"},
    {"name": "last_seen", "type": "Utf8"},
    {"name": "project", "type": "Utf8"},
    {"name": "query", "type": "Utf8"},
]
GITHUB_COLS = [
    {"name": "number", "type": "Int64", "nullable": False},
    {"name": "title", "type": "Utf8"},
    {"name": "state", "type": "Utf8"},
    {"name": "merged", "type": "Boolean"},
    {"name": "draft", "type": "Boolean"},
    {"name": "body", "type": "Utf8"},
    {"name": "user__login", "type": "Utf8"},
    {"name": "user", "type": "Utf8"},
    {"name": "base__ref", "type": "Utf8"},
    {"name": "head__label", "type": "Utf8"},
    {"name": "created_at", "type": "Utf8"},
    {"name": "merged_at", "type": "Utf8"},
    {"name": "closed_at", "type": "Utf8"},
    {"name": "updated_at", "type": "Utf8"},
    {"name": "html_url", "type": "Utf8"},
    {"name": "additions", "type": "Int64"},
    {"name": "deletions", "type": "Int64"},
    {"name": "changed_files", "type": "Int64"},
    {"name": "comments", "type": "Int64"},
    {"name": "commits", "type": "Int64"},
    {"name": "mergeable_state", "type": "Utf8"},
    {"name": "owner", "type": "Utf8"},
    {"name": "repo", "type": "Utf8"},
]
SLACK_COLS = [
    {"name": "user_id", "type": "Utf8"},
    {"name": "text", "type": "Utf8"},
    {"name": "ts", "type": "Utf8"},
    {"name": "channel", "type": "Utf8"},
    {"name": "permalink", "type": "Utf8"},
    {"name": "reply_count", "type": "Int64"},
    {"name": "thread_ts", "type": "Utf8"},
    {"name": "subtype", "type": "Utf8"},
]


def _make_yaml(name: str, table: str, description: str, location: str,
               columns: list[dict]) -> str:
    cols = "\n".join(
        f"      - {{name: {c['name']}, type: {c['type']}, "
        f"nullable: {str(c.get('nullable', True)).lower()}}}"
        for c in columns
    )
    return f"""\
name: {name}
version: "1.0.0"
dsl_version: 3
backend: jsonl
description: {description}
tables:
  - name: {table}
    description: {description}
    source:
      location: {location}
      glob: "{table}.jsonl"
    columns:
{cols}
"""


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_jsonl(path: str, records: list[dict]) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")
    logger.info("Wrote %d records to %s", len(records), path)


def write_yaml(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content.lstrip("\n"))
    logger.info("Wrote manifest to %s", path)


def generate_all(output_dir: str = BASE_DIR) -> None:
    abs_dir = os.path.abspath(output_dir)
    file_prefix = f"file://{abs_dir}"

    # Sentry
    sentry_dir = os.path.join(abs_dir, "sentry")
    ensure_dir(sentry_dir)
    write_jsonl(os.path.join(sentry_dir, "issues.jsonl"), SENTRY_ISSUES)
    write_yaml(os.path.join(abs_dir, "sentry.yaml"),
               _make_yaml("mock_sentry", "issues",
                          "Mock Sentry error groups",
                          f"file://{sentry_dir}", SENTRY_COLS))

    # Datadog
    datadog_dir = os.path.join(abs_dir, "datadog")
    ensure_dir(datadog_dir)
    write_jsonl(os.path.join(datadog_dir, "incidents.jsonl"), DATADOG_INCIDENTS)

    # GitHub
    github_dir = os.path.join(abs_dir, "github")
    ensure_dir(github_dir)
    write_jsonl(os.path.join(github_dir, "pulls.jsonl"), GITHUB_PULLS)
    write_yaml(os.path.join(abs_dir, "github.yaml"),
               _make_yaml("mock_github", "pulls",
                          "Mock GitHub pull requests",
                          f"file://{github_dir}", GITHUB_COLS))

    # PagerDuty
    pagerduty_dir = os.path.join(abs_dir, "pagerduty")
    ensure_dir(pagerduty_dir)
    write_jsonl(os.path.join(pagerduty_dir, "incidents.jsonl"), PD_INCIDENTS)
    write_jsonl(os.path.join(pagerduty_dir, "oncalls.jsonl"), PD_ONCALLS)

    # Slack
    slack_dir = os.path.join(abs_dir, "slack")
    ensure_dir(slack_dir)
    write_jsonl(os.path.join(slack_dir, "messages.jsonl"), SLACK_MESSAGES)
    write_yaml(os.path.join(abs_dir, "slack.yaml"),
               _make_yaml("mock_slack", "messages",
                          "Mock Slack messages",
                          f"file://{slack_dir}", SLACK_COLS))

    logger.info("=" * 60)
    logger.info("Realistic incident mock data generated in: %s", output_dir)
    logger.info("Incident: CDN Cache Key config drift (inspired by Cloudflare + Fastly outages)")
    logger.info("  sentry  : %d issues (spike → recovery)", len(SENTRY_ISSUES))
    logger.info("  datadog : %d incidents (auto-detected alerts)", len(DATADOG_INCIDENTS))
    logger.info("  github  : %d pull requests (cause + revert + fixes)", len(GITHUB_PULLS))
    logger.info("  pagerduty: %d incidents + %d oncalls", len(PD_INCIDENTS), len(PD_ONCALLS))
    logger.info("  slack   : %d messages (incident response + postmortem)", len(SLACK_MESSAGES))
    logger.info("=" * 60)


def activate_sources(output_dir: str = BASE_DIR) -> None:
    coral_cmd = os.environ.get("CORAL_COMMAND", "coral")

    sources = [
        ("mock_sentry", os.path.join(output_dir, "sentry.yaml")),
        ("mock_github", os.path.join(output_dir, "github.yaml")),
        ("mock_slack", os.path.join(output_dir, "slack.yaml")),
    ]

    for name, manifest_path in sources:
        result = subprocess.run(
            [coral_cmd, "source", "add", "--file", manifest_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Source '%s' added successfully", name)
        else:
            stderr = result.stderr.strip()
            if "already exists" in stderr:
                logger.info("Source '%s' already exists (skipping)", name)
            else:
                logger.warning("Failed to add source '%s': %s", name, stderr)

    for name, _ in sources:
        result = subprocess.run(
            [coral_cmd, "source", "test", name],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Source '%s' connectivity OK", name)
        else:
            logger.warning("Source '%s' test failed: %s", name, result.stderr.strip())

    logger.info("Mock sources activated.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate realistic incident mock data"
    )
    parser.add_argument("--output", type=str, default=BASE_DIR)
    parser.add_argument("--activate", action="store_true",
                        help="Also add/register mock sources with Coral")
    return parser.parse_args()


def main():
    args = parse_args()
    generate_all(args.output)
    if args.activate:
        activate_sources(args.output)
    else:
        logger.info("Run with --activate to register mock sources with Coral.")


if __name__ == "__main__":
    main()
