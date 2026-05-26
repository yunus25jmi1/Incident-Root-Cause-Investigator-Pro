"""
End-to-end mock-based integration test: simulates a full investigation
from mention → queue → agent → formatted report, using mocked dependencies.
"""

import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from investigator.agent.coral_client import CoralClient, QueryResult
from investigator.agent.core import AgentCore
from investigator.bot.queue import InvestigationQueue
from investigator.bot.formatter import (
    investigation_report,
    postmortem_report,
    error_message,
    help_message,
    progress_update,
    _sanitize_mrkdwn,
)


def _mock_multi_source_rows():
    return {
        "sentry": QueryResult(rows=[{
            "id": "1", "title": "ZeroDivisionError in CheckoutController.check()",
            "level": "error", "count": 847, "user_count": 312,
            "first_seen": "2026-05-24T14:32:00Z",
            "last_seen": "2026-05-24T14:55:00Z",
            "project": "checkout-service",
        }], row_count=1, columns=[]),
        "datadog": QueryResult(rows=[{
            "id": "dd-inc-001", "title": "High error rate on checkout-service",
            "severity": "SEV-2", "customer_impacted": True,
            "created": "2026-05-24T14:33:00Z",
        }], row_count=1, columns=[]),
        "github": QueryResult(rows=[{
            "title": "fix: checkout validation",
            "merged_at": "2026-05-24T14:30:00Z",
            "html_url": "https://github.com/org/repo/pull/4321",
            "state": "merged", "user__login": "Alice", "base__ref": "main",
        }], row_count=1, columns=[]),
        "pagerduty": QueryResult(rows=[{
            "id": "INC789", "title": "Checkout SEV-2",
            "status": "triggered", "urgency": "high",
            "created_at": "2026-05-24T14:35:00Z",
        }], row_count=1, columns=[]),
        "slack": QueryResult(rows=[
            {"user_id": "U001", "text": "Anyone looking at this?", "ts": "1621877700.000100"},
            {"user_id": "U002", "text": "I see the error spike on checkout", "ts": "1621877800.000200"},
        ], row_count=2, columns=[]),
    }


@pytest.mark.asyncio
async def test_full_investigation_flow():
    """End-to-end: mock Coral → AgentCore → investigation report → valid Slack blocks."""
    mock_coral = AsyncMock(spec=CoralClient)

    async def mock_query(sql: str):
        for key, result in _mock_multi_source_rows().items():
            if key in sql.lower() or key.replace("_", ".") in sql.lower():
                return result
        return QueryResult(rows=[], row_count=0, columns=[])

    mock_coral.query = mock_query
    agent = AgentCore(mock_coral, incidents_channel="incidents")

    report = await agent.investigate("what caused the 5xx spike on checkout?")

    assert report["incident_id"] == "INC789"
    assert "Alice" in report["summary"]
    assert len(report["evidence_chain"]) >= 3
    assert len(report["people_involved"]) >= 1
    assert len(report["suggested_actions"]) >= 1
    assert report["confidence"] is not None

    blocks = investigation_report(report)
    assert len(blocks) >= 3
    blocks_json = json.dumps(blocks)
    assert "Incident Analysis Report" in blocks_json
    assert "section" in blocks_json
    assert any(b.get("type") == "section" for b in blocks)


@pytest.mark.asyncio
async def test_full_flow_via_queue():
    """End-to-end: enqueue via InvestigationQueue with all mocks."""
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "987.654"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    reasoning = AsyncMock()
    reasoning.classify_intent = AsyncMock(return_value="investigate")

    coral = AsyncMock()
    coral.__aenter__ = AsyncMock(return_value=coral)
    coral.__aexit__ = AsyncMock(return_value=None)

    async def mock_query(sql: str):
        for key, result in _mock_multi_source_rows().items():
            if key in sql.lower() or key.replace("_", ".") in sql.lower():
                return result
        return QueryResult(rows=[], row_count=0, columns=[])

    coral.query = mock_query

    agent = AsyncMock()
    agent.investigate_with_reasoning = AsyncMock(return_value={
        "title": "5xx Spike Analysis",
        "summary": "PR #4321 (Alice) → ZeroDivisionError spike → INC789",
        "sources": {
            "sentry": {"status": "ok", "count": 1},
            "datadog": {"status": "ok", "count": 1},
            "github": {"status": "ok", "count": 1},
            "pagerduty": {"status": "ok", "count": 1},
            "slack": {"status": "ok", "count": 2},
        },
        "evidence_chain": [
            {"type": "deploy", "title": "PR #4321 merged", "detail": "by Alice",
             "time": "14:30", "url": "https://github.com/org/repo/pull/4321"},
            {"type": "error", "title": "ZeroDivisionError spike", "detail": "847 errors",
             "time": "14:32", "url": ""},
            {"type": "incident", "title": "SEV-2 on checkout", "detail": "Customer impacted",
             "time": "14:33", "url": ""},
            {"type": "page", "title": "PagerDuty: checkout SEV-2", "detail": "Urgency: high",
             "time": "14:35", "url": ""},
            {"type": "discussion", "title": "Slack: U001", "detail": "Anyone looking at this?",
             "time": "1621877700.000100", "url": ""},
        ],
        "people_involved": [
            {"name": "Alice", "role": "PR author"},
            {"name": "Bob Smith", "role": "On-call SRE"},
        ],
        "suggested_actions": [
            {"priority": "P0", "description": "Revert PR #4321"},
            {"priority": "P1", "description": "Add null check in CheckoutController.check()"},
        ],
        "errors": {},
        "confidence": "High",
        "timestamp": "2026-05-26T12:00:00Z",
    })

    with (
        patch("investigator.bot.queue.ReasoningEngine", return_value=reasoning),
        patch("investigator.bot.queue.CoralClient", return_value=coral),
        patch("investigator.bot.queue.AgentCore", return_value=agent),
    ):
        queue = InvestigationQueue(mock_client, incidents_channel="incidents")

        await queue.enqueue(
            "what caused the 5xx spike?",
            "C01", "ts-original", since="3h", service="checkout-service",
        )
        await asyncio.sleep(0.3)

        mock_client.chat_postMessage.assert_called()
        mock_client.chat_update.assert_called()

        final_update = None
        for call in mock_client.chat_update.call_args_list:
            if "Incident Analysis Report" in (call.kwargs.get("text", "") or ""):
                final_update = call
                break
        assert final_update is not None, "Final report not posted"


@pytest.mark.asyncio
async def test_help_intent_flow():
    """Help intent shortcut returns help blocks instead of running investigation."""
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "111.222"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    reasoning = AsyncMock()
    reasoning.classify_intent = AsyncMock(return_value="help")

    with patch("investigator.bot.queue.ReasoningEngine", return_value=reasoning):
        queue = InvestigationQueue(mock_client)
        await queue.enqueue("help", "C01", "ts1")
        await asyncio.sleep(0.2)

        chat_update_calls = mock_client.chat_update.call_args_list
        help_blocks = None
        for call in chat_update_calls:
            if "Need help?" in (call.kwargs.get("text", "") or ""):
                help_blocks = call.kwargs.get("blocks")
                break
        assert help_blocks is not None
        help_text = str(help_blocks)
        assert "Investigator Pro Help" in help_text or "investigator" in help_text.lower()


@pytest.mark.asyncio
async def test_chat_intent_flow():
    """Chat intent returns a conversational reply."""
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "111.222"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    reasoning = AsyncMock()
    reasoning.classify_intent = AsyncMock(return_value="chat")
    reasoning.chat_response = AsyncMock(return_value="Hello! I can help investigate incidents.")

    with patch("investigator.bot.queue.ReasoningEngine", return_value=reasoning):
        queue = InvestigationQueue(mock_client)
        await queue.enqueue("hi there", "C01", "ts1")
        await asyncio.sleep(0.2)

        chat_update_calls = mock_client.chat_update.call_args_list
        chat_text = None
        for call in chat_update_calls:
            text = call.kwargs.get("text", "")
            if "Hello" in text:
                chat_text = text
                break
        assert chat_text is not None
        assert "Hello" in chat_text


@pytest.mark.asyncio
async def test_postmortem_intent_flow_via_queue():
    """Postmortem intent routes to /postmortem instruction."""
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "111.222"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    reasoning = AsyncMock()
    reasoning.classify_intent = AsyncMock(return_value="postmortem")

    with patch("investigator.bot.queue.ReasoningEngine", return_value=reasoning):
        queue = InvestigationQueue(mock_client)
        await queue.enqueue("generate postmortem for INC789", "C01", "ts1")
        await asyncio.sleep(0.2)

        update_calls = mock_client.chat_update.call_args_list
        pm_text = None
        for call in update_calls:
            text = call.kwargs.get("text", "")
            if "/postmortem" in text:
                pm_text = text
                break
        assert pm_text is not None
        assert "--incident" in pm_text


class TestSanitizeMrkdwn:
    def test_sanitizes_all_mentions(self):
        text = "alert <!channel> and <!everyone> and <!here>"
        result = _sanitize_mrkdwn(text)
        assert "[channel]" in result
        assert "[everyone]" in result
        assert "[here]" in result
        assert "<!channel>" not in result

    def test_sanitizes_nested_brackets(self):
        text = "check <!channel|here>"
        result = _sanitize_mrkdwn(text)
        assert "[channel]" in result
        assert "<!channel|here>" not in result


class TestProgressBlocks:
    def test_progress_update_chain(self):
        p1 = progress_update("🔍", "starting")
        p2 = progress_update("📡", "phase 1")
        p3 = progress_update("✅", "done")
        assert "🔍" in p1
        assert "📡" in p2
        assert "✅" in p3

    def test_no_broken_unicode(self):
        text = progress_update("🚨", "test")
        assert isinstance(text, str)
        assert len(text) > 0


class TestReportBlocks:
    def test_postmortem_empty(self):
        blocks = postmortem_report({})
        assert len(blocks) > 0
        assert any("Post-Incident Review" in str(b) for b in blocks)

    def test_error_message_empty(self):
        blocks = error_message("")
        assert len(blocks) > 0

    def test_help_message_structure(self):
        blocks = help_message()
        text = str(blocks)
        assert "investigator" in text.lower()
        assert "/postmortem" in text


def test_all_blocks_serializable():
    report = {
        "summary": "test", "evidence_chain": [], "people_involved": [],
        "suggested_actions": [], "sources": {}, "errors": {},
        "confidence": "Low", "timestamp": "",
    }
    for builder, args in [
        (investigation_report, (report,)),
        (postmortem_report, (report,)),
        (error_message, ("err",)),
        (help_message, ()),
    ]:
        blocks = builder(*args)
        s = json.dumps(blocks)
        assert len(s) > 0
