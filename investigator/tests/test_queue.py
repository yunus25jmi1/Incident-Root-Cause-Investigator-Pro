import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investigator.bot.queue import InvestigationQueue


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.fixture(autouse=True)
def mock_deps():
    reasoning = AsyncMock()
    reasoning.classify_intent = AsyncMock(return_value="investigate")

    coral = AsyncMock()
    coral.__aenter__ = AsyncMock(return_value=coral)
    coral.__aexit__ = AsyncMock(return_value=None)

    agent = AsyncMock()
    agent.investigate_with_reasoning = AsyncMock(return_value={
        "title": "Test Report", "summary": "Investigation complete",
        "sources": [], "evidence_chain": [], "people": [], "actions": [],
    })

    with (
        patch("investigator.bot.queue.ReasoningEngine", return_value=reasoning),
        patch("investigator.bot.queue.CoralClient", return_value=coral),
        patch("investigator.bot.queue.AgentCore", return_value=agent),
    ):
        yield


@pytest.fixture
def queue(mock_client):
    return InvestigationQueue(
        mock_client,
        incidents_channel="test-incidents",
        max_queue_size=3,
    )


@pytest.mark.asyncio
async def test_enqueue_starts_worker(queue, mock_client):
    await queue.enqueue("test question", "C01", "ts1")
    assert queue.is_worker_running is True
    await asyncio.sleep(0.1)
    mock_client.chat_postMessage.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_sets_channel_and_thread(queue, mock_client):
    await queue.enqueue("test question", "C01", "ts1")
    await asyncio.sleep(0.1)
    assert mock_client.chat_postMessage.call_args.kwargs["channel"] == "C01"
    assert mock_client.chat_postMessage.call_args.kwargs["thread_ts"] == "ts1"


@pytest.mark.asyncio
async def test_enqueue_rejects_when_full(queue, mock_client):
    queue._queue.full = lambda: True

    await queue.enqueue("overflow", "C01", "ts1")
    full_call = None
    for call in mock_client.chat_postMessage.call_args_list:
        if "Queue is full" in (call.kwargs.get("text", "") or ""):
            full_call = call
            break
    assert full_call is not None


@pytest.mark.asyncio
async def test_cancels_worker_task(queue):
    await queue.enqueue("test", "C01", "ts1")
    await asyncio.sleep(0.05)
    await queue.cancel()
    assert queue.is_worker_running is False


@pytest.mark.asyncio
async def test_cancel_with_no_worker(queue):
    await queue.cancel()
    assert queue.is_worker_running is False


@pytest.mark.asyncio
async def test_multiple_enqueues(queue):
    await queue.enqueue("q1", "C01", "ts1")
    await queue.enqueue("q2", "C01", "ts1")
    await asyncio.sleep(0.3)
    assert queue.is_worker_running is True


@pytest.mark.asyncio
async def test_worker_restarts_after_cancel(queue):
    await queue.enqueue("q1", "C01", "ts1")
    await asyncio.sleep(0.05)
    await queue.cancel()
    assert queue.is_worker_running is False
    await queue.enqueue("q2", "C01", "ts1")
    await asyncio.sleep(0.05)
    assert queue.is_worker_running is True


@pytest.mark.asyncio
async def test_enqueue_with_flags(queue, mock_client):
    await queue.enqueue("test", "C01", "ts1", since="24h", service="api-gateway")
    await asyncio.sleep(0.1)
    mock_client.chat_postMessage.assert_called_once()


@pytest.mark.asyncio
async def test_worker_handles_timeout_error(queue, mock_client):
    queue._process = AsyncMock(side_effect=asyncio.TimeoutError())

    await queue.enqueue("test", "C01", "ts1")
    await asyncio.sleep(0.1)
    assert queue.is_worker_running is True


@pytest.mark.asyncio
async def test_worker_continues_after_exception(queue):
    call_count = 0

    async def flaky_process(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("first failure")

    queue._process = flaky_process

    await queue.enqueue("q1", "C01", "ts1")
    await asyncio.sleep(0.15)
    await queue.enqueue("q2", "C01", "ts1")
    await asyncio.sleep(0.15)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_enqueue_none_worker_after_full_then_drain(queue, mock_client):
    queue._queue.full = lambda: True

    await queue.enqueue("overflow", "C01", "ts1")
    full_calls = [
        c for c in mock_client.chat_postMessage.call_args_list
        if "Queue is full" in (c.kwargs.get("text", "") or "")
    ]
    assert len(full_calls) == 1
    assert queue.is_worker_running is False
