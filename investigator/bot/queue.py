import asyncio
import json
import logging
import os
from asyncio import Queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from slack_sdk.errors import SlackApiError

from investigator.agent.coral_client import CoralClient
from investigator.agent.core import AgentCore
from investigator.lib.secrets_refresher import SecretsRefresher
from investigator.agent.reasoning import ReasoningEngine
from investigator.lib.redis_persistence import RedisQueuePersistence
from investigator.bot.formatter import (
    investigation_report,
    error_message,
    help_message,
    progress_update,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE_SIZE = 10
QUEUE_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "queue_state.jsonl"


class QueueEncrypter:
    def __init__(self):
        self._fernet = None
        key = os.environ.get("QUEUE_ENCRYPTION_KEY", "").strip()
        if key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
            except Exception as e:
                logger.warning("QUEUE_ENCRYPTION_KEY set but invalid: %s - falling back to plaintext", e)

    def encrypt(self, data: bytes) -> bytes:
        if self._fernet:
            return self._fernet.encrypt(data)
        return data

    def decrypt(self, data: bytes) -> bytes:
        if self._fernet:
            try:
                return self._fernet.decrypt(data)
            except Exception as e:
                logger.warning("Queue state decryption failed: %s", e)
        return data


class QueuePersistence:
    def __init__(self, path: Path = QUEUE_STATE_PATH, encrypter: Optional[QueueEncrypter] = None):
        self._path = path
        self._encrypter = encrypter or QueueEncrypter()

    def save(self, item: tuple) -> None:
        question, channel, thread_ts, since, service = item
        entry = {
            "question": question,
            "channel": channel,
            "thread_ts": thread_ts,
            "since": since,
            "service": service,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = json.dumps(entry) + "\n"
            encrypted = self._encrypter.encrypt(raw.encode())
            with open(self._path, "ab") as f:
                f.write(encrypted + b"\n")
        except Exception as e:
            logger.warning("Failed to save queue state: %s", e)

    async def async_save(self, item: tuple) -> None:
        self.save(item)

    def remove(self, item: tuple) -> None:
        question, channel, thread_ts, since, service = item
        try:
            if not self._path.exists():
                return
            raw = self._path.read_bytes()
            lines = raw.split(b"\n")
            kept = []
            for line in lines:
                if not line.strip():
                    continue
                decrypted = self._encrypter.decrypt(line)
                try:
                    entry = json.loads(decrypted)
                    if (entry.get("question") == question
                            and entry.get("channel") == channel
                            and entry.get("thread_ts") == thread_ts):
                        continue
                    kept.append(line)
                except (json.JSONDecodeError, Exception):
                    continue
            self._path.write_bytes(b"\n".join(kept) + b"\n" if kept else b"")
        except Exception as e:
            logger.warning("Failed to remove queue state: %s", e)

    async def async_remove(self, item: tuple) -> None:
        self.remove(item)

    @classmethod
    def load(cls, path: Path = QUEUE_STATE_PATH, encrypter: Optional[QueueEncrypter] = None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        _enc = encrypter or QueueEncrypter()
        entries = []
        try:
            for line in path.read_bytes().split(b"\n"):
                if line.strip():
                    decrypted = _enc.decrypt(line)
                    try:
                        entries.append(json.loads(decrypted))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Failed to load queue state: %s", e)
            return []
        return entries

    @classmethod
    def clear(cls, path: Path = QUEUE_STATE_PATH) -> None:
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("Failed to clear queue state: %s", e)


class InvestigationQueue:
    def __init__(
        self,
        slack_client,
        incidents_channel: str = "incidents",
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        persistence: Optional[QueuePersistence] = None,
        coral: Optional[CoralClient] = None,
    ):
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task | None = None
        self._client = slack_client
        self._incidents_channel = incidents_channel
        self._processed_count = 0
        if persistence is None:
            _redis_p = RedisQueuePersistence()
            self._persistence = _redis_p if _redis_p.is_available() else QueuePersistence()
        else:
            self._persistence = persistence
        self._current_item: Optional[tuple] = None
        self._coral = coral

    @property
    def processed_count(self) -> int:
        return self._processed_count

    @property
    def is_worker_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    async def enqueue(
        self, question: str, channel: str, thread_ts: str,
        since: str = "", service: str = "",
    ):
        if self._queue.full():
            try:
                await self._client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="Queue is full. Please wait for the current investigation to complete.",
                )
            except Exception as e:
                logger.warning("Failed to notify channel %s about full queue: %s", channel, e)
            return
        item = (question, channel, thread_ts, since, service)
        await self._queue.put(item)
        await self._persistence.async_save(item)
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())
            logger.info("Investigation worker started")

    async def _run(self):
        while True:
            try:
                self._current_item = await self._queue.get()
                question, channel, thread_ts, since, service = self._current_item
                await self._process(question, channel, thread_ts, since=since, service=service)
                self._current_item = None
            except asyncio.CancelledError:
                logger.info("Investigation worker cancelled")
                break
            except Exception as e:
                logger.exception("Investigation worker error: %s", e)
                self._current_item = None

    async def _process(
        self, question: str, channel: str, thread_ts: str,
        since: str = "", service: str = "",
    ):
        status_ts: str | None = None
        try:
            try:
                result = await self._client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=progress_update("🔍", "Investigating..."),
                )
            except SlackApiError as e:
                if e.response.get("error") == "channel_not_found":
                    logger.warning("Channel %s not found — removing from queue", channel)
                    if self._current_item:
                        await self._persistence.async_remove(self._current_item)
                    return
                raise
            status_ts = result.get("ts")
            if not status_ts:
                status_ts = result["message"]["ts"]

            reasoning = ReasoningEngine()
            intent = await reasoning.classify_intent(question)

            if intent == "help":
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text="Need help?",
                    blocks=help_message(),
                )
                return

            if intent == "chat":
                reply = await reasoning.chat_response(question)
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text=reply,
                    blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": reply}}],
                )
                return

            if intent == "postmortem":
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text="Use `/postmortem --incident INC123` to generate a review.",
                    blocks=[{"type": "section", "text": {
                        "type": "mrkdwn",
                        "text": "To generate a post-incident review, use the "
                                "`/postmortem --incident INC123` command.",
                    }}],
                )
                return

            if intent == "lookup":
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text=progress_update("📡", "Fetching data..."),
                )
                coral = self._coral if (self._coral and self._coral.is_connected) else await CoralClient().__aenter__()
                phase1 = await AgentCore.run_phase1_queries(coral, since="24h")
                answer = await reasoning.lookup_answer(question, phase1, coral.query)
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text=answer,
                    blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": answer}}],
                )
                return

            async def on_progress(emoji: str, text: str):
                await self._update_status(channel, status_ts, progress_update(emoji, text))

            await SecretsRefresher().refresh_if_changed()

            if self._coral and self._coral.is_connected:
                coral = self._coral
            else:
                coral_cm = CoralClient()
                await coral_cm.connect()
                coral = coral_cm
            agent = AgentCore(coral, incidents_channel=self._incidents_channel)
            report = await agent.investigate_with_reasoning(
                question, on_progress=on_progress,
                since=since, service=service,
            )

            blocks = investigation_report(report)
            await self._client.chat_update(
                channel=channel,
                ts=status_ts,
                text="🚨 Incident Analysis Report",
                blocks=blocks,
            )
            if self._current_item:
                await self._persistence.async_remove(self._current_item)
            logger.info("Investigation complete for channel=%s", channel)
            self._processed_count += 1

        except asyncio.TimeoutError:
            error = "Investigation timed out. Coral may be unavailable."
            await self._post_error(channel, thread_ts, status_ts, error)
            if self._current_item:
                await self._persistence.async_remove(self._current_item)
        except Exception as e:
            logger.exception("Investigation failed")
            await self._post_error(channel, thread_ts, status_ts, str(e))
            if self._current_item:
                await self._persistence.async_remove(self._current_item)

    async def _update_status(self, channel: str, ts: str, text: str):
        try:
            await self._client.chat_update(channel=channel, ts=ts, text=text)
        except Exception as e:
            logger.warning("Failed to update status: %s", e)

    async def _post_error(
        self, channel: str, thread_ts: str,
        status_ts: str | None, error_text: str,
    ):
        blocks = error_message("Investigation Failed", error_text)
        if status_ts:
            try:
                await self._client.chat_update(
                    channel=channel, ts=status_ts,
                    text="❌ Investigation failed",
                    blocks=blocks,
                )
                return
            except Exception:
                logger.warning("Failed to update error status, posting new message")
        try:
            await self._client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text="❌ Investigation failed",
                blocks=blocks,
            )
        except Exception as e:
            logger.warning("Failed to post error message to channel %s: %s", channel, e)

    async def cancel(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
