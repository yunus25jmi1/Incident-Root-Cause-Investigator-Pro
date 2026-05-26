"""
Seed Sentry with test error data for the incident investigation demo.

Usage:
    export SENTRY_DSN="https://..."
    python -m investigator.scripts.seed_sentry

This pushes 100 ZeroDivisionError events to correlate with a
hypothetical checkout-service PR merge scenario.
"""

import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_env() -> str:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.error("SENTRY_DSN environment variable is not set.")
        logger.error("Usage: export SENTRY_DSN='https://...'")
        sys.exit(1)
    if not dsn.startswith("https://"):
        logger.warning("SENTRY_DSN should typically start with https://")
    return dsn


def seed_errors(dsn: str, count: int = 100, delay: float = 0.1) -> int:
    try:
        import sentry_sdk
    except ImportError:
        logger.error(
            "sentry-sdk is not installed. Install it with: pip install sentry-sdk"
        )
        sys.exit(1)

    sentry_sdk.init(dsn=dsn)
    logger.info("Sentry SDK initialized with DSN: %s...", dsn[:30])

    sentry_sdk.set_tag("service", "checkout-service")
    sentry_sdk.set_tag("version", "v2.14.1")
    sentry_sdk.set_context("deploy", {
        "pr_number": 4321,
        "author": "Alice",
        "branch": "fix/checkout-validation",
    })

    success_count = 0
    for i in range(count):
        try:
            sentry_sdk.set_tag("attempt", i + 1)
            sentry_sdk.set_extra("iteration", i + 1)
            1 / 0
        except ZeroDivisionError:
            sentry_sdk.capture_exception()
            success_count += 1
        time.sleep(delay)

        if (i + 1) % 25 == 0:
            logger.info("Seeded %d/%d errors...", i + 1, count)

    logger.info("Successfully seeded %d errors to Sentry", success_count)
    return success_count


def main():
    dsn = validate_env()
    count = int(os.environ.get("SENTRY_ERROR_COUNT", "100"))
    delay = float(os.environ.get("SENTRY_SEED_DELAY", "0.1"))
    logger.info("Starting Sentry seeding: %d errors with %.1fs delay", count, delay)
    seed_errors(dsn, count=count, delay=delay)
    logger.info("Seeding complete.")


if __name__ == "__main__":
    main()
