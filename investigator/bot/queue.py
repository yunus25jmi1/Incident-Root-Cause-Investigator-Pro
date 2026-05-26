import asyncio
import logging
from asyncio import Queue
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


class InvestigationQueue:
    def __init__(
        self,
        slack_client,
        incidents_channel: str = "incidents",
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ):
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task | None = None
        self._client = slack_client
        self._incidents_channel = incidents_channel
        self._processed_count = 0

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
        await self._queue.put((question, channel, thread_ts, since, service))
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())
            logger.info("Investigation worker started")

    async def _run(self):
        while True:
            try:
                item = await self._queue.get()
                question, channel, thread_ts, since, service = item
                await self._process(question, channel, thread_ts, since=since, service=service)
            except asyncio.CancelledError:
                logger.info("Investigation worker cancelled")
                break
            except Exception as e:
                logger.exception("Investigation worker error: %s", e)

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
