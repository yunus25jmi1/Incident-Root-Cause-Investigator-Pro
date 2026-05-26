"""
Generate 30-40 precise mock records per source matching real Coral schemas.

Sources: sentry, datadog, github, pagerduty, slack
Output: JSONL files + YAML manifests for mock imported sources

Usage:
    python -m investigator.scripts.seed_all
    python -m investigator.scripts.seed_all --activate  # activate as live mock sources
"""

import argparse
import json
import logging
import os
import shutil
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sources", "mocks")
)
NOW = datetime(2026, 5, 27, 4, 0, 0, tzinfo=timezone.utc)


def dt(offset_hours: float) -> str:
    return (NOW + timedelta(hours=offset_hours)).isoformat().replace("+00:00", "Z")


# ── Sentry Issues ────────────────────────────────────────────────────
SENTRY_ISSUES = [
    # Incident 1: PR merge broke checkout (May 24, ~36h ago)
    dict(id="SENT-001", short_id="SENTRY-1A", title="ZeroDivisionError in CheckoutController.calculate_total",
         status="unresolved", level="error", count=847, user_count=312,
         first_seen=dt(-36.5), last_seen=dt(-36.0), project="checkout-service",
         query="ZeroDivisionError CheckoutController"),
    dict(id="SENT-002", short_id="SENTRY-2B", title="NullReferenceException in PaymentGateway.authorize",
         status="unresolved", level="fatal", count=423, user_count=189,
         first_seen=dt(-36.3), last_seen=dt(-35.9), project="payment-service",
         query="NullReferenceException PaymentGateway"),
    dict(id="SENT-003", short_id="SENTRY-3C", title="TypeError: Cannot read properties of undefined (reading 'price')",
         status="unresolved", level="error", count=215, user_count=98,
         first_seen=dt(-36.2), last_seen=dt(-35.8), project="checkout-service",
         query="TypeError price undefined"),
    # Incident 2: Database slowdown (May 25, ~12h ago)
    dict(id="SENT-004", short_id="SENTRY-4D", title="ConnectionTimeoutError: Unable to acquire connection from pool",
         status="unresolved", level="error", count=1560, user_count=534,
         first_seen=dt(-12.5), last_seen=dt(-12.0), project="api-gateway",
         query="ConnectionTimeoutError pool"),
    dict(id="SENT-005", short_id="SENTRY-5E", title="psycopg2.OperationalError: FATAL: too many connections",
         status="unresolved", level="fatal", count=892, user_count=401,
         first_seen=dt(-12.4), last_seen=dt(-11.9), project="user-service",
         query="OperationalError too many connections"),
    dict(id="SENT-006", short_id="SENTRY-6F", title="Django.db.utils.DatabaseError: deadlock detected",
         status="unresolved", level="error", count=334, user_count=145,
         first_seen=dt(-12.3), last_seen=dt(-11.8), project="order-service",
         query="DatabaseError deadlock"),
    # Incident 3: Config drift (May 26, ~8h ago)
    dict(id="SENT-007", short_id="SENTRY-7G", title="Http502Error: upstream connect error or disconnect/reset before headers",
         status="unresolved", level="error", count=2100, user_count=876,
         first_seen=dt(-8.5), last_seen=dt(-8.0), project="checkout-service",
         query="Http502Error upstream"),
    dict(id="SENT-008", short_id="SENTRY-8H", title="EnvoyBadResponse: upstream connection error",
         status="unresolved", level="error", count=1100, user_count=512,
         first_seen=dt(-8.4), last_seen=dt(-7.9), project="api-gateway",
         query="EnvoyBadResponse upstream"),
    # Scattered warnings and low-severity issues
    dict(id="SENT-009", short_id="SENTRY-9I", title="MemoryWarning: heap allocation exceeded 1GB",
         status="unresolved", level="warning", count=45, user_count=12,
         first_seen=dt(-48.0), last_seen=dt(-2.0), project="checkout-service",
         query="MemoryWarning heap"),
    dict(id="SENT-010", short_id="SENTRY-10J", title="SlowQueryWarning: SELECT on orders table took 12.3s",
         status="unresolved", level="warning", count=78, user_count=23,
         first_seen=dt(-72.0), last_seen=dt(-6.0), project="order-service",
         query="SlowQueryWarning orders"),
    dict(id="SENT-011", short_id="SENTRY-11K", title="RateLimitWarning: API rate limit at 85%",
         status="unresolved", level="warning", count=23, user_count=8,
         first_seen=dt(-24.0), last_seen=dt(-4.0), project="api-gateway",
         query="RateLimitWarning rate limit"),
    dict(id="SENT-012", short_id="SENTRY-12L", title="ValidationError: Invalid email format in signup",
         status="resolved", level="error", count=156, user_count=89,
         first_seen=dt(-96.0), last_seen=dt(-48.0), project="user-service",
         query="ValidationError email"),
    dict(id="SENT-013", short_id="SENTRY-13M", title="IntegrityError: duplicate key value violates unique constraint",
         status="resolved", level="error", count=67, user_count=34,
         first_seen=dt(-72.0), last_seen=dt(-36.0), project="user-service",
         query="IntegrityError duplicate key"),
    dict(id="SENT-014", short_id="SENTRY-14N", title="KeyError: 'discount_code' not found in session",
         status="unresolved", level="error", count=234, user_count=112,
         first_seen=dt(-18.0), last_seen=dt(-6.0), project="checkout-service",
         query="KeyError discount_code"),
    dict(id="SENT-015", short_id="SENTRY-15O", title="JSONDecodeError: Unexpected token in response body",
         status="unresolved", level="error", count=89, user_count=45,
         first_seen=dt(-24.0), last_seen=dt(-10.0), project="payment-service",
         query="JSONDecodeError response"),
    dict(id="SENT-016", short_id="SENTRY-16P", title="TimeoutError: Request to shipping-service timed out after 30s",
         status="unresolved", level="error", count=412, user_count=178,
         first_seen=dt(-20.0), last_seen=dt(-5.0), project="order-service",
         query="TimeoutError shipping-service"),
    dict(id="SENT-017", short_id="SENTRY-17Q", title="IndexError: list index out of range in InventoryService.get_stock",
         status="unresolved", level="error", count=56, user_count=28,
         first_seen=dt(-30.0), last_seen=dt(-12.0), project="inventory-service",
         query="IndexError get_stock"),
    dict(id="SENT-018", short_id="SENTRY-18R", title="ValueError: invalid literal for int() with base 10: 'N/A'",
         status="unresolved", level="error", count=123, user_count=67,
         first_seen=dt(-40.0), last_seen=dt(-15.0), project="inventory-service",
         query="ValueError int base 10"),
    dict(id="SENT-019", short_id="SENTRY-19S", title="AttributeError: 'NoneType' object has no attribute 'get'",
         status="unresolved", level="error", count=345, user_count=156,
         first_seen=dt(-28.0), last_seen=dt(-8.0), project="checkout-service",
         query="AttributeError NoneType get"),
    dict(id="SENT-020", short_id="SENTRY-20T", title="RuntimeError: Event loop is closed",
         status="unresolved", level="error", count=12, user_count=5,
         first_seen=dt(-50.0), last_seen=dt(-3.0), project="api-gateway",
         query="RuntimeError event loop closed"),
    dict(id="SENT-021", short_id="SENTRY-21U", title="AssertionError: Expected 200 OK but got 503",
         status="unresolved", level="error", count=78, user_count=34,
         first_seen=dt(-16.0), last_seen=dt(-7.0), project="checkout-service",
         query="AssertionError 503"),
    dict(id="SENT-022", short_id="SENTRY-22V", title="RecursionError: maximum recursion depth exceeded",
         status="unresolved", level="error", count=5, user_count=2,
         first_seen=dt(-100.0), last_seen=dt(-50.0), project="order-service",
         query="RecursionError depth"),
    dict(id="SENT-023", short_id="SENTRY-23W", title="FileNotFoundError: config.yaml not found in /etc/app/",
         status="resolved", level="error", count=1, user_count=1,
         first_seen=dt(-120.0), last_seen=dt(-119.0), project="deploy-service",
         query="FileNotFoundError config.yaml"),
    dict(id="SENT-024", short_id="SENTRY-24X", title="PermissionError: Access denied to S3 bucket production-logs",
         status="unresolved", level="error", count=34, user_count=12,
         first_seen=dt(-60.0), last_seen=dt(-5.0), project="infra-service",
         query="PermissionError S3"),
    dict(id="SENT-025", short_id="SENTRY-25Y", title="Warning: Deprecated API /v1/checkout used by mobile client",
         status="unresolved", level="warning", count=890, user_count=450,
         first_seen=dt(-96.0), last_seen=dt(-1.0), project="checkout-service",
         query="Deprecated API v1 checkout"),
    dict(id="SENT-026", short_id="SENTRY-26Z", title="OSError: [Errno 24] Too many open files",
         status="unresolved", level="error", count=67, user_count=23,
         first_seen=dt(-14.0), last_seen=dt(-6.0), project="api-gateway",
         query="OSError too many open files"),
    dict(id="SENT-027", short_id="SENTRY-27A", title="Exception: Unhandled promise rejection in payment-webhook",
         status="unresolved", level="error", count=234, user_count=89,
         first_seen=dt(-22.0), last_seen=dt(-9.0), project="payment-service",
         query="Unhandled promise rejection"),
    dict(id="SENT-028", short_id="SENTRY-28B", title="SSLHandshakeError: certificate verify failed",
         status="resolved", level="error", count=12, user_count=4,
         first_seen=dt(-200.0), last_seen=dt(-150.0), project="payment-service",
         query="SSLHandshakeError certificate"),
    dict(id="SENT-029", short_id="SENTRY-29C", title="OverflowError: integer overflow in discount calculation",
         status="unresolved", level="error", count=45, user_count=18,
         first_seen=dt(-10.0), last_seen=dt(-4.0), project="checkout-service",
         query="OverflowError discount"),
    dict(id="SENT-030", short_id="SENTRY-30D", title="LookupError: No matching shipping rate for destination",
         status="unresolved", level="error", count=89, user_count=56,
         first_seen=dt(-15.0), last_seen=dt(-2.0), project="order-service",
         query="LookupError shipping rate"),
    dict(id="SENT-031", short_id="SENTRY-31E", title="NotImplementedError: Bulk discount not implemented for region EU",
         status="resolved", level="warning", count=3, user_count=1,
         first_seen=dt(-300.0), last_seen=dt(-48.0), project="checkout-service",
         query="NotImplementedError bulk discount"),
    dict(id="SENT-032", short_id="SENTRY-32F", title="UnboundLocalError: local variable 'total' referenced before assignment",
         status="unresolved", level="error", count=156, user_count=67,
         first_seen=dt(-18.0), last_seen=dt(-6.0), project="checkout-service",
         query="UnboundLocalError total"),
    dict(id="SENT-033", short_id="SENTRY-33G", title="ConnectionResetError: [Errno 104] Connection reset by peer",
         status="unresolved", level="error", count=445, user_count=189,
         first_seen=dt(-12.0), last_seen=dt(-3.0), project="api-gateway",
         query="ConnectionResetError 104"),
    dict(id="SENT-034", short_id="SENTRY-34H", title="Warning: High latency on /api/checkout endpoint (avg 4.5s)",
         status="unresolved", level="warning", count=230, user_count=120,
         first_seen=dt(-24.0), last_seen=dt(-1.0), project="checkout-service",
         query="High latency checkout"),
    dict(id="SENT-035", short_id="SENTRY-35I", title="BrokenPipeError: [Errno 32] Broken pipe writing to redis",
         status="unresolved", level="error", count=78, user_count=34,
         first_seen=dt(-8.0), last_seen=dt(-2.0), project="checkout-service",
         query="BrokenPipeError redis"),
]

# ── Datadog Incidents ────────────────────────────────────────────────
DATADOG_INCIDENTS = [
    dict(id="dd-inc-001", title="High error rate on checkout-service", status="active",
         severity="SEV-2", created=dt(-36.5), modified=dt(-35.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-002", title="Database connection pool exhaustion", status="active",
         severity="SEV-3", created=dt(-12.5), modified=dt(-11.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-003", title="Deployment config drift - HTTP 502 errors", status="active",
         severity="SEV-2", created=dt(-8.5), modified=dt(-7.5), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-004", title="Payment gateway latency spike", status="resolved",
         severity="SEV-3", created=dt(-48.0), modified=dt(-46.0), resolved_at=dt(-45.0), customer_impacted=True),
    dict(id="dd-inc-005", title="Inventory sync failure", status="resolved",
         severity="SEV-4", created=dt(-72.0), modified=dt(-70.0), resolved_at=dt(-69.0), customer_impacted=False),
    dict(id="dd-inc-006", title="SSL certificate expiry on api-gateway", status="resolved",
         severity="SEV-3", created=dt(-96.0), modified=dt(-94.0), resolved_at=dt(-90.0), customer_impacted=True),
    dict(id="dd-inc-007", title="Redis cluster node failure", status="active",
         severity="SEV-3", created=dt(-10.0), modified=dt(-9.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-008", title="Order processing backlog", status="active",
         severity="SEV-4", created=dt(-6.0), modified=dt(-5.0), resolved_at=None, customer_impacted=False),
    dict(id="dd-inc-009", title="CDN cache purge failure", status="resolved",
         severity="SEV-5", created=dt(-120.0), modified=dt(-119.0), resolved_at=dt(-118.0), customer_impacted=False),
    dict(id="dd-inc-010", title="Shipping rate API degradation", status="active",
         severity="SEV-3", created=dt(-14.0), modified=dt(-13.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-011", title="Memory leak on checkout containers", status="active",
         severity="SEV-3", created=dt(-20.0), modified=dt(-18.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-012", title="Docker registry pull rate limit", status="resolved",
         severity="SEV-4", created=dt(-168.0), modified=dt(-166.0), resolved_at=dt(-165.0), customer_impacted=False),
    dict(id="dd-inc-013", title="Elasticsearch cluster yellow status", status="active",
         severity="SEV-4", created=dt(-4.0), modified=dt(-3.0), resolved_at=None, customer_impacted=False),
    dict(id="dd-inc-014", title="Kubernetes pod crash loop on payment", status="active",
         severity="SEV-2", created=dt(-7.0), modified=dt(-6.0), resolved_at=None, customer_impacted=True),
    dict(id="dd-inc-015", title="PostgreSQL replication lag exceeds 10s", status="active",
         severity="SEV-3", created=dt(-3.0), modified=dt(-2.0), resolved_at=None, customer_impacted=True),
]

# ── GitHub Pulls ─────────────────────────────────────────────────────
GITHUB_PULLS = [
    dict(number=4321, title="fix: add null check in CheckoutController.calculate_total",
         state="merged", merged=True, draft=False, body="Adds null check for price parameter to prevent ZeroDivisionError",
         user__login="Alice", user="Alice", base__ref="main", head__label="fix/checkout-validation",
         created_at=dt(-48.0), merged_at=dt(-36.5), closed_at=dt(-36.5), updated_at=dt(-36.4),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4321",
         additions=42, deletions=8, changed_files=3, comments=5, commits=2, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4322, title="feat: add discount code validation middleware",
         state="merged", merged=True, draft=False,
         body="Validates discount codes before passing to payment gateway",
         user__login="Bob", user="Bob", base__ref="main", head__label="feat/discount-validation",
         created_at=dt(-48.0), merged_at=dt(-36.0), closed_at=dt(-36.0), updated_at=dt(-35.9),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4322",
         additions=85, deletions=12, changed_files=5, comments=3, commits=3, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4323, title="fix: increase DB connection pool size to 50",
         state="merged", merged=True, draft=False,
         body="Increases max_connections from 20 to 50 to handle traffic spikes",
         user__login="Charlie", user="Charlie", base__ref="main", head__label="fix/db-pool-size",
         created_at=dt(-24.0), merged_at=dt(-12.5), closed_at=dt(-12.5), updated_at=dt(-12.4),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4323",
         additions=15, deletions=5, changed_files=2, comments=8, commits=1, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4324, title="revert: 'fix: increase DB connection pool size to 50'",
         state="merged", merged=True, draft=False,
         body="Reverts pool size increase - caused connection exhaustion",
         user__login="Diana", user="Diana", base__ref="main", head__label="revert/db-pool-fix",
         created_at=dt(-12.0), merged_at=dt(-11.5), closed_at=dt(-11.5), updated_at=dt(-11.4),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4324",
         additions=5, deletions=15, changed_files=2, comments=4, commits=1, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4325, title="fix: correct nginx config for checkout upstream",
         state="merged", merged=True, draft=False,
         body="Fixes proxy_pass directive that was pointing to old deployment",
         user__login="Alice", user="Alice", base__ref="main", head__label="fix/nginx-checkout-config",
         created_at=dt(-16.0), merged_at=dt(-8.5), closed_at=dt(-8.5), updated_at=dt(-8.4),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4325",
         additions=8, deletions=4, changed_files=1, comments=6, commits=2, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4326, title="feat: add circuit breaker pattern for payment calls",
         state="merged", merged=True, draft=False,
         body="Implements circuit breaker with 50% failure threshold",
         user__login="Bob", user="Bob", base__ref="main", head__label="feat/circuit-breaker",
         created_at=dt(-72.0), merged_at=dt(-60.0), closed_at=dt(-60.0), updated_at=dt(-59.9),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4326",
         additions=120, deletions=30, changed_files=8, comments=12, commits=5, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4327, title="chore: upgrade redis client to v4.5.0",
         state="merged", merged=True, draft=False,
         body="Updates redis-py from 3.5.3 to 4.5.0 for connection stability fixes",
         user__login="Charlie", user="Charlie", base__ref="main", head__label="chore/redis-upgrade",
         created_at=dt(-20.0), merged_at=dt(-10.0), closed_at=dt(-10.0), updated_at=dt(-9.9),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4327",
         additions=25, deletions=25, changed_files=3, comments=2, commits=1, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4328, title="fix: handle SSL certificate rotation for payment webhook",
         state="merged", merged=True, draft=False,
         body="Updates cert store and adds cert expiry monitoring",
         user__login="Diana", user="Diana", base__ref="main", head__label="fix/ssl-rotation",
         created_at=dt(-100.0), merged_at=dt(-96.0), closed_at=dt(-96.0), updated_at=dt(-95.9),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4328",
         additions=60, deletions=10, changed_files=4, comments=7, commits=3, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4329, title="WIP: migrate checkout to new pricing engine",
         state="open", merged=False, draft=True,
         body="Work in progress - migrating pricing logic to microservice",
         user__login="Alice", user="Alice", base__ref="main", head__label="feat/new-pricing-engine",
         created_at=dt(-6.0), merged_at=None, closed_at=None, updated_at=dt(-2.0),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4329",
         additions=450, deletions=200, changed_files=25, comments=3, commits=8, mergeable_state="dirty",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4330, title="fix: add retry logic for shipping API calls",
         state="open", merged=False, draft=False,
         body="Implements exponential backoff retry for third-party shipping API",
         user__login="Bob", user="Bob", base__ref="main", head__label="fix/shipping-retry",
         created_at=dt(-4.0), merged_at=None, closed_at=None, updated_at=dt(-1.0),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4330",
         additions=35, deletions=5, changed_files=2, comments=1, commits=2, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
    dict(number=4331, title="feat: add request tracing headers to all services",
         state="open", merged=False, draft=False,
         body="Adds X-Request-ID and X-Trace-ID headers for distributed tracing",
         user__login="Charlie", user="Charlie", base__ref="main", head__label="feat/tracing-headers",
         created_at=dt(-8.0), merged_at=None, closed_at=None, updated_at=dt(-3.0),
         html_url="https://github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro/pull/4331",
         additions=200, deletions=0, changed_files=15, comments=5, commits=6, mergeable_state="clean",
         owner="yunus25jmi1", repo="Incident-Root-Cause-Investigator-Pro"),
]

# ── PagerDuty Incidents ──────────────────────────────────────────────
PD_INCIDENTS = [
    dict(id="INC789", title="Checkout service errors spike - SEV-2",
         status="triggered", urgency="high", created_at=dt(-36.3), escalation_level=1,
         escalation_policy_id="EP001"),
    dict(id="INC790", title="Database connection pool exhaustion - SEV-3",
         status="triggered", urgency="medium", created_at=dt(-12.3), escalation_level=1,
         escalation_policy_id="EP002"),
    dict(id="INC791", title="Deployment config drift - HTTP 502 errors",
         status="triggered", urgency="high", created_at=dt(-8.3), escalation_level=2,
         escalation_policy_id="EP003"),
    dict(id="INC792", title="Payment gateway latency spike - SEV-3",
         status="acknowledged", urgency="medium", created_at=dt(-48.0), escalation_level=1,
         escalation_policy_id="EP001"),
    dict(id="INC793", title="Redis cluster node failure",
         status="triggered", urgency="high", created_at=dt(-10.0), escalation_level=1,
         escalation_policy_id="EP002"),
    dict(id="INC794", title="Kubernetes pod crash loop on payment-service",
         status="triggered", urgency="high", created_at=dt(-7.0), escalation_level=2,
         escalation_policy_id="EP003"),
    dict(id="INC795", title="Shipping rate API degradation",
         status="acknowledged", urgency="medium", created_at=dt(-14.0), escalation_level=1,
         escalation_policy_id="EP001"),
    dict(id="INC796", title="Memory leak on checkout containers",
         status="triggered", urgency="medium", created_at=dt(-20.0), escalation_level=1,
         escalation_policy_id="EP002"),
    dict(id="INC797", title="PostgreSQL replication lag exceeds threshold",
         status="triggered", urgency="high", created_at=dt(-3.0), escalation_level=1,
         escalation_policy_id="EP003"),
    dict(id="INC798", title="SSL certificate expiry warning",
         status="resolved", urgency="low", created_at=dt(-96.0), escalation_level=1,
         escalation_policy_id="EP001"),
    dict(id="INC799", title="Inventory sync failure",
         status="resolved", urgency="low", created_at=dt(-72.0), escalation_level=1,
         escalation_policy_id="EP002"),
    dict(id="INC800", title="CDN cache purge failure",
         status="resolved", urgency="low", created_at=dt(-120.0), escalation_level=1,
         escalation_policy_id="EP003"),
    dict(id="INC801", title="Docker registry pull rate limit hit",
         status="resolved", urgency="low", created_at=dt(-168.0), escalation_level=1,
         escalation_policy_id="EP001"),
    dict(id="INC802", title="Elasticsearch cluster yellow status",
         status="acknowledged", urgency="low", created_at=dt(-4.0), escalation_level=1,
         escalation_policy_id="EP002"),
    dict(id="INC803", title="Order processing backlog growing",
         status="triggered", urgency="medium", created_at=dt(-6.0), escalation_level=1,
         escalation_policy_id="EP003"),
]

PD_ONCALLS = [
    dict(id="oncall-001", escalation_policy_id="EP001", escalation_level=1,
         name="Bob Smith", email="bob@company.com"),
    dict(id="oncall-002", escalation_policy_id="EP001", escalation_level=2,
         name="Alice", email="alice@company.com"),
    dict(id="oncall-003", escalation_policy_id="EP002", escalation_level=1,
         name="Diana Chen", email="diana@company.com"),
    dict(id="oncall-004", escalation_policy_id="EP002", escalation_level=2,
         name="Charlie", email="charlie@company.com"),
    dict(id="oncall-005", escalation_policy_id="EP003", escalation_level=1,
         name="Frank Miller", email="frank@company.com"),
    dict(id="oncall-006", escalation_policy_id="EP003", escalation_level=2,
         name="Bob Smith", email="bob@company.com"),
]

# ── Slack Messages ───────────────────────────────────────────────────
SLACK_MESSAGES = [
    dict(user_id="U06M7PADT29", text="<@U0B6Z6LMJ80> what caused the 5xx spike?",
         ts=dt(-36.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p1", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Looking into it now. Seeing errors in checkout-service. <@U06M7PADT29>",
         ts=dt(-35.9), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p2", reply_count=2, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="I noticed PR #4321 was merged about 30 min before the spike started",
         ts=dt(-35.8), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p3", reply_count=3, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="Can someone revert PR #4321?",
         ts=dt(-35.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p4", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Revert PR is up: #4324. Also the DB pool fix from earlier seems related.",
         ts=dt(-35.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p5", reply_count=5, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Database connection pool is completely exhausted. Running query to check active connections.",
         ts=dt(-12.4), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p6", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="PagerDuty INC790 triggered for DB pool. Who's on call?",
         ts=dt(-12.3), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p7", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Diana is on call for DB issues. I'll escalate to her.",
         ts=dt(-12.2), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p8", reply_count=4, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Reverting the pool size increase fixed the immediate issue. Monitoring now.",
         ts=dt(-11.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p9", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="We're getting 502 errors on checkout now! <@U0B6Z6LMJ80>",
         ts=dt(-8.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p10", reply_count=3, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Likely config drift from the deploy. Check nginx config on the new instances.",
         ts=dt(-8.4), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p11", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Found it. The new deployment didn't pick up the updated nginx config. Fix in #4325.",
         ts=dt(-8.3), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p12", reply_count=2, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="Good catch. Let's make sure config sync is automated for next time.",
         ts=dt(-8.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p13", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="I'll create a postmortem ticket for this. Three incidents in three days is too many.",
         ts=dt(-7.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p14", reply_count=5, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="Alert: Redis node in cluster-us-east-1a is down. <@U0B6Z6LMJ80>",
         ts=dt(-10.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p15", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Seeing payment failures. Is the circuit breaker working?",
         ts=dt(-9.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p16", reply_count=3, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Pod crash loop in payment-service. OOMKilled. <@U06M7PADT29>",
         ts=dt(-7.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p17", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Memory leak seems to be getting worse. Let's increase memory limits temporarily.",
         ts=dt(-6.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p18", reply_count=2, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="Has anyone reviewed the shipping API degradation? Customers complaining about slow checkout.",
         ts=dt(-14.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p19", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Shipping API is timing out. Their SLA says 2s response but we're seeing 15s+",
         ts=dt(-13.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p20", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Opened PR #4330 with retry logic for shipping API. ETA 30 min.",
         ts=dt(-4.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p21", reply_count=1, thread_ts=None, subtype=None),
    dict(user_id="U06M7PADT29", text="PostgreSQL replication lag is at 15s. Need to investigate. <@U0B68GEFG3K>",
         ts=dt(-3.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p22", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B68GEFG3K", text="Looking at replica lag now. The write volume doubled in the last hour.",
         ts=dt(-2.5), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p23", reply_count=0, thread_ts=None, subtype=None),
    dict(user_id="U0B6Z6LMJ80", text="Postmortem for INC789, INC790, INC791 scheduled for tomorrow 10am.",
         ts=dt(-1.0), channel="C0B68EU1909",
         permalink="https://slack.com/archives/C0B68EU1909/p24", reply_count=0, thread_ts=None, subtype=None),
]

# ── Source YAML manifests ─────────────────────────────────────────────
def _make_yaml(name: str, table: str, description: str, location: str,
               columns: list[dict]) -> str:
    cols = "\n".join(
        f"      - {{name: {c['name']}, type: {c['type']}, nullable: {str(c.get('nullable', True)).lower()}}}"
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

    sentry_cols = [
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
    github_cols = [
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
    slack_cols = [
        {"name": "user_id", "type": "Utf8"},
        {"name": "text", "type": "Utf8"},
        {"name": "ts", "type": "Utf8"},
        {"name": "channel", "type": "Utf8"},
        {"name": "permalink", "type": "Utf8"},
        {"name": "reply_count", "type": "Int64"},
        {"name": "thread_ts", "type": "Utf8"},
        {"name": "subtype", "type": "Utf8"},
    ]

    # Sentry
    sentry_dir = os.path.join(abs_dir, "sentry")
    ensure_dir(sentry_dir)
    write_jsonl(os.path.join(sentry_dir, "issues.jsonl"), SENTRY_ISSUES)
    write_yaml(os.path.join(abs_dir, "sentry.yaml"),
               _make_yaml("mock_sentry", "issues",
                          "Mock Sentry error groups for incident investigation demo",
                          f"file://{sentry_dir}", sentry_cols))

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
                          "Mock GitHub pull requests for incident investigation demo",
                          f"file://{github_dir}", github_cols))

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
                          "Mock Slack messages for incident investigation demo",
                          f"file://{slack_dir}", slack_cols))

    logger.info("=" * 60)
    logger.info("All mock data generated in: %s", output_dir)
    logger.info("  sentry  : %d issues", len(SENTRY_ISSUES))
    logger.info("  datadog : %d incidents", len(DATADOG_INCIDENTS))
    logger.info("  github  : %d pull requests", len(GITHUB_PULLS))
    logger.info("  pagerduty: %d incidents, %d oncalls", len(PD_INCIDENTS), len(PD_ONCALLS))
    logger.info("  slack   : %d messages", len(SLACK_MESSAGES))
    logger.info("=" * 60)


def activate_sources(output_dir: str = BASE_DIR) -> None:
    """Copy JSONL files to the default names Coral expects, add sources."""
    import subprocess

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

    # Test connectivity
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
        description="Generate comprehensive mock data for all incident sources"
    )
    parser.add_argument("--output", type=str, default=BASE_DIR,
                        help="Output directory (default: sources/mocks/)")
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
