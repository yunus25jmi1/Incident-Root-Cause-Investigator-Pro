import asyncio
import json
import logging
from asyncio import Queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from investigator.agent.coral_client import CoralClient
from investigator.agent.core import AgentCore
from investigator.agent.reasoning import ReasoningEngine
from investigator.bot.formatter import (
    investigation_report,
    error_message,
    help_message,
    progress_update,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE_SIZE = 10
QUEUE_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "queue_state.jsonl"


class QueuePersistence:
    def __init__(self, path: Path = QUEUE_STATE_PATH):
        self._path = path

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
            with open(self._path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning("Failed to save queue state: %s", e)

    def remove(self, item: tuple) -> None:
        question, channel, thread_ts, since, service = item
        try:
            if not self._path.exists():
                return
            lines = self._path.read_text().splitlines()
            kept = []
            for line in lines:
                try:
                    entry = json.loads(line)
                    if (entry.get("question") == question
                            and entry.get("channel") == channel
                            and entry.get("thread_ts") == thread_ts):
                        continue
                    kept.append(line)
                except json.JSONDecodeError:
                    continue
            self._path.write_text("\n".join(kept) + "\n" if kept else "")
        except Exception as e:
            logger.warning("Failed to remove queue state: %s", e)

    @classmethod
    def load(cls, path: Path = QUEUE_STATE_PATH) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries = []
        try:
            for line in path.read_text().splitlines():
                if line.strip():
                    try:
                        entries.append(json.loads(line))
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
    ):
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task | None = None
        self._client = slack_client
        self._incidents_channel = incidents_channel
        self._processed_count = 0
        self._persistence = persistence or QueuePersistence()
        self._current_item: Optional[tuple] = None

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
            await self._client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Queue is full. Please wait for the current investigation to complete.",
            )
            return
        item = (question, channel, thread_ts, since, service)
        await self._queue.put(item)
        self._persistence.save(item)
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
            result = await self._client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=progress_update("🔍", "Investigating..."),
            )
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

            async def on_progress(emoji: str, text: str):
                await self._update_status(channel, status_ts, progress_update(emoji, text))

            async with CoralClient() as coral:
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
                self._persistence.remove(self._current_item)
            logger.info("Investigation complete for channel=%s", channel)
            self._processed_count += 1

        except asyncio.TimeoutError:
            error = "Investigation timed out. Coral may be unavailable."
            await self._post_error(channel, thread_ts, status_ts, error)
        except Exception as e:
            logger.exception("Investigation failed")
            await self._post_error(channel, thread_ts, status_ts, str(e))

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
        await self._client.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text="❌ Investigation failed",
            blocks=blocks,
        )

    async def cancel(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
