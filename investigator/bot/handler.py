import os
import asyncio
import re
import json
import logging
import signal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.util.utils import get_boot_message

from investigator.agent.coral_client import CoralClient
from investigator.bot.queue import InvestigationQueue, QueuePersistence
from investigator.lib.rate_limiter import RateLimiter
from investigator.lib.redis_persistence import RedisRateLimiter
from investigator.lib.sanitizer import ErrorSanitizer
from investigator.bot.formatter import (
    postmortem_report,
    error_message,
    help_message,
    not_authorized_message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    raise ValueError(
        "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set in .env"
    )

ALLOWED_CHANNELS_RAW = os.environ.get("ALLOWED_CHANNELS", "")
ALLOWED_CHANNELS = [
    c.strip() for c in ALLOWED_CHANNELS_RAW.split(",") if c.strip()
]
INCIDENTS_CHANNEL = os.environ.get("INCIDENTS_CHANNEL", "incidents")
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "10"))
# CORAL_COMMAND should be an absolute path in .env to prevent PATH hijacking
RATE_LIMIT_PER_WINDOW = int(os.environ.get("RATE_LIMIT_PER_WINDOW", "10"))
RATE_LIMIT_WINDOW_SECONDS = 60.0
MAX_QUESTION_LENGTH = 5000

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = AsyncApp(token=SLACK_BOT_TOKEN)
investigation_queue: "InvestigationQueue | None" = None
_redis_rl = RedisRateLimiter(max_requests=RATE_LIMIT_PER_WINDOW, window_seconds=RATE_LIMIT_WINDOW_SECONDS)
rate_limiter = _redis_rl if _redis_rl._r else RateLimiter(max_requests=RATE_LIMIT_PER_WINDOW, window_seconds=RATE_LIMIT_WINDOW_SECONDS)


def is_channel_allowed(channel_id: str) -> bool:
    if not ALLOWED_CHANNELS:
        return True
    return channel_id in ALLOWED_CHANNELS


def _sanitize_id(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw)[:128]


def _is_valid_channel(channel: str) -> bool:
    return bool(re.fullmatch(r"C[A-Z0-9]{8,}", channel))


def parse_flags(text: str) -> tuple[str, str, str]:
    since = ""
    service = ""
    since_match = re.search(r"--since\s+(\S+)", text)
    if since_match:
        since = since_match.group(1)
        text = text.replace(since_match.group(0), "")
    service_match = re.search(r"--service\s+(\S+)", text)
    if service_match:
        service = service_match.group(1)
        text = text.replace(service_match.group(0), "")
    return text.strip(), since, service


def extract_question(event: dict) -> str:
    text = event.get("text", "")
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    return text[:MAX_QUESTION_LENGTH]


def parse_postmortem_args(text: str) -> dict:
    incident_match = re.search(r"--incident\s+(\S+)", text)
    raw = incident_match.group(1) if incident_match else None
    return {
        "incident_id": _sanitize_id(raw) if raw else None,
    }


@app.event("app_mention")
async def handle_mention(event: dict, say, client):
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts", event.get("ts", ""))
    user_id = event.get("user", event.get("user_id", "unknown"))

    if not is_channel_allowed(channel):
        await say(
            text="Channel not authorized",
            blocks=not_authorized_message(),
            thread_ts=thread_ts,
        )
        return

    if await rate_limiter.is_rate_limited(user_id):
        remaining = await rate_limiter.remaining(user_id)
        logger.warning("Rate limited user=%s channel=%s", user_id, channel)
        await say(
            text=f"Rate limited. You can send {remaining} more request(s) per 60s.",
            thread_ts=thread_ts,
        )
        return

    raw_question = extract_question(event)
    question, since_flag, service_flag = parse_flags(raw_question)
    if not question:
        await say(
            text="Please ask a question about an incident.",
            blocks=help_message(),
            thread_ts=thread_ts,
        )
        return

    logger.info(
        "Mention received: user=%s channel=%s, question=%s, since=%s, service=%s",
        user_id, channel, question[:100], since_flag or "default", service_flag or "none",
    )
    await investigation_queue.enqueue(
        question, channel, thread_ts, since=since_flag, service=service_flag,
    )


@app.command("/postmortem")
async def handle_postmortem(command: dict, say, client):
    channel = command.get("channel_id", "")
    text = command.get("text", "")
    args = parse_postmortem_args(text)
    incident_id = args.get("incident_id")

    if not incident_id:
        await say(
            text="Usage: `/postmortem --incident INC123`",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Please specify an incident ID.\n"
                        "Usage: `/postmortem --incident INC123`",
                    },
                }
            ],
        )
        return

    report_file = REPORTS_DIR / f"{incident_id}.json"
    if not report_file.exists():
        await say(
            text=f"📝 No saved investigation found for {incident_id}. "
            f"Run `@investigator` first to investigate this incident.",
            thread_ts=command.get("ts", ""),
        )
        return

    try:
        with open(report_file) as f:
            report = json.load(f)
        blocks = postmortem_report(report)
        await say(
            text=f"📝 Post-Incident Review: {incident_id}",
            blocks=blocks,
        )
        logger.info("Postmortem generated for %s", incident_id)
    except Exception as e:
        logger.exception("Failed to generate postmortem")
        await say(
            text=f"Failed to generate postmortem: {e}",
            blocks=error_message("Postmortem Generation Failed", str(e)),
        )


@app.error
async def global_error_handler(error, body, logger):
    logger.exception("Global error: %s", error)
    safe_error = ErrorSanitizer.sanitize(str(error))
    safe_error = ErrorSanitizer.truncate(safe_error)
    logger.warning("Sanitized global error: %s", safe_error)


async def main():
    _dsn = os.environ.get("SENTRY_DSN", "").strip()
    if _dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=_dsn, traces_sample_rate=0.1)
            logger.info("Sentry SDK initialized")
        except Exception as e:
            logger.warning("Failed to init Sentry SDK: %s", e)

    coral = CoralClient()
    try:
        await coral.connect()
        logger.info("Coral MCP connected (pre-warmed)")
    except Exception as e:
        logger.warning("Coral MCP pre-warm failed (will connect per-investigation): %s", e)
        coral = None

    try:
        global investigation_queue
        investigation_queue = InvestigationQueue(
            app.client,
            incidents_channel=INCIDENTS_CHANNEL,
            max_queue_size=MAX_QUEUE_SIZE,
            coral=coral,
        )

        saved_entries = QueuePersistence.load()
        if saved_entries:
            logger.info("Restoring %d saved queue entries", len(saved_entries))
            for entry in saved_entries:
                if entry.get("status") != "pending":
                    continue
                channel = entry.get("channel", "")
                if not _is_valid_channel(channel):
                    logger.warning("Skipping restore entry with invalid channel=%s", channel)
                    continue
                try:
                    await investigation_queue.enqueue(
                        entry["question"],
                        channel,
                        entry.get("thread_ts", ""),
                        since=entry.get("since", ""),
                        service=entry.get("service", ""),
                    )
                except Exception as e:
                    logger.warning("Failed to restore queue entry (channel may be dead): %s", e)
            QueuePersistence.clear()

        loop = asyncio.get_event_loop()
        shutdown_event = asyncio.Event()

        async def _signal_shutdown():
            logger.info("Shutdown signal received")
            if investigation_queue:
                await investigation_queue.cancel()
            await handler.close_async()
            shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(_signal_shutdown()))
            except NotImplementedError:
                pass

        logger.info("Starting Investigator Pro bot (Socket Mode)...")
        handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
        await handler.connect_async()
        handler.app.logger.info(get_boot_message())
        await shutdown_event.wait()
    finally:
        if coral and coral.is_connected:
            await coral.disconnect()
            logger.info("Coral MCP disconnected")


if __name__ == "__main__":
    asyncio.run(main())
