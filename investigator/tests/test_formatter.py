import pytest
from investigator.bot.formatter import (
    progress_block,
    progress_update,
    investigation_report,
    postmortem_report,
    error_message,
    help_message,
    not_authorized_message,
    _sanitize_mrkdwn,
)


class TestProgressBlocks:
    def test_progress_block_structure(self):
        blocks = progress_block("🔍", "Investigating...")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert "🔍 Investigating..." in blocks[0]["text"]["text"]

    def test_progress_update_string(self):
        text = progress_update("📡", "Gathering data...")
        assert text == "📡 Gathering data..."

    def test_progress_update_emoji_only(self):
        text = progress_update("✅", "")
        assert text == "✅ "

    def test_progress_truncates_long_text(self):
        long_text = "x" * 5000
        text = progress_update("🔍", long_text)
        assert len(text) < 5005


class TestInvestigationReport:
    def test_empty_report(self):
        blocks = investigation_report({})
        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"

    def test_minimal_report(self):
        import json
        report = {
            "summary": "Test summary",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "High",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = investigation_report(report)
        assert any("Test summary" in json.dumps(b) for b in blocks)

    def test_full_report_with_evidence(self):
        report = {
            "summary": "PR #4321 caused error spike",
            "evidence_chain": [
                {
                    "type": "deploy",
                    "title": "PR #4321 merged",
                    "detail": "by Alice",
                    "time": "14:30",
                    "url": "https://github.com/pr/4321",
                },
                {
                    "type": "error",
                    "title": "NPE spike",
                    "detail": "847 occurrences",
                    "time": "14:32",
                    "url": "",
                },
            ],
            "people_involved": [
                {"name": "Alice", "role": "PR author"},
                {"name": "Bob", "role": "On-call SRE"},
            ],
            "suggested_actions": [
                {"priority": "P0", "description": "Revert PR #4321"},
                {"priority": "P1", "description": "Add null check"},
            ],
            "sources": {
                "sentry": {"status": "ok", "count": 5},
                "github": {"status": "ok", "count": 3},
                "datadog": {"status": "empty", "count": 0},
            },
            "errors": {},
            "confidence": "High",
            "question": "what caused the 5xx spike?",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = investigation_report(report)
        assert len(blocks) > 5
        blocks_str = str(blocks)
        assert "PR #4321 merged" in blocks_str
        assert "Alice" in blocks_str
        assert "P0" in blocks_str
        assert "NPE spike" in blocks_str

    def test_report_with_errors(self):
        report = {
            "summary": "Partial data",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {"datadog": "Connection refused", "pagerduty": "Source not configured"},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        assert "datadog" in blocks_str
        assert "Connection refused" in blocks_str

    def test_report_truncates_long_evidence(self):
        report = {
            "summary": "Test",
            "evidence_chain": [
                {"title": f"Item {i}", "detail": "", "time": "", "url": ""}
                for i in range(20)
            ],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        for i in range(10):
            assert f"Item {i}" in blocks_str
        assert "Item 15" not in blocks_str

    def test_evidence_chain_missing_url(self):
        report = {
            "summary": "Test with missing URL",
            "evidence_chain": [
                {"type": "error", "title": "Error title", "detail": "details", "time": "14:00", "url": ""},
            ],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        assert "Error title" in blocks_str

    def test_evidence_chain_string_items(self):
        report = {
            "summary": "String items",
            "evidence_chain": ["Step 1", "Step 2", "Step 3"],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        assert "Step 1" in blocks_str

    def test_people_as_strings(self):
        report = {
            "summary": "People as strings",
            "evidence_chain": [],
            "people_involved": ["Alice", "Bob", "Charlie"],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        assert "Alice" in blocks_str

    def test_actions_as_strings(self):
        report = {
            "summary": "Actions as strings",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": ["Fix null check", "Revert PR"],
            "sources": {},
            "errors": {},
            "confidence": "Low",
            "timestamp": "",
        }
        blocks = investigation_report(report)
        blocks_str = str(blocks)
        assert "Fix null check" in blocks_str


class TestPostmortemReport:
    def test_postmortem_empty(self):
        blocks = postmortem_report({})
        assert len(blocks) > 0
        assert "Post-Incident Review" in str(blocks)

    def test_postmortem_with_data(self):
        report = {
            "incident_id": "INC789",
            "summary": "Null pointer in checkout",
            "question": "what caused the 5xx spike?",
            "evidence_chain": [
                {"title": "PR merged", "detail": "by Alice", "time": "14:30"},
                {"title": "Error spike", "detail": "847 errors", "time": "14:32"},
            ],
            "people_involved": [
                {"name": "Alice", "role": "Developer"},
                {"name": "Bob", "role": "SRE"},
            ],
            "suggested_actions": [
                {"priority": "P0", "description": "Add null check"},
            ],
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = postmortem_report(report)
        blocks_str = str(blocks)
        assert "INC789" in blocks_str
        assert "Alice" in blocks_str
        assert "P0" in blocks_str
        assert "14:30" in blocks_str

    def test_postmortem_with_string_actions(self):
        report = {
            "incident_id": "INC790",
            "summary": "DB timeout",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": ["Fix connection pool", "Add monitoring"],
            "timestamp": "",
        }
        blocks = postmortem_report(report)
        blocks_str = str(blocks)
        assert "Fix connection pool" in blocks_str
        assert "- [ ]" in blocks_str


class TestErrorMessage:
    def test_error_with_title_only(self):
        blocks = error_message("Something went wrong")
        blocks_str = str(blocks)
        assert "Something went wrong" in blocks_str

    def test_error_with_details(self):
        blocks = error_message("Connection failed", "Timeout after 30s")
        blocks_str = str(blocks)
        assert "Connection failed" in blocks_str
        assert "Timeout after 30s" in blocks_str

    def test_error_long_details_truncated(self):
        long_details = "x" * 5000
        blocks = error_message("Error", long_details)
        blocks_str = str(blocks)
        assert len(blocks_str) < 6000


class TestHelpMessage:
    def test_help_structure(self):
        blocks = help_message()
        assert any("Investigator Pro Help" in str(b) for b in blocks)
        assert any("@investigator" in str(b) for b in blocks)
        assert any("/postmortem" in str(b) for b in blocks)


class TestNotAuthorizedMessage:
    def test_not_authorized(self):
        blocks = not_authorized_message()
        blocks_str = str(blocks)
        assert "not authorized" in blocks_str.lower()
        assert "ALLOWED_CHANNELS" in blocks_str


def _import_json():
    import json
    return json


def test_all_blocks_are_valid_json():
    report = {
        "summary": "Test",
        "evidence_chain": [],
        "people_involved": [],
        "suggested_actions": [],
        "sources": {},
        "errors": {},
        "confidence": "Low",
        "timestamp": "",
    }
    for builder, args in [
        (progress_block, ("🔍", "test")),
        (investigation_report, (report,)),
        (postmortem_report, (report,)),
        (error_message, ("error", "details")),
        (help_message, ()),
        (not_authorized_message, ()),
    ]:
        blocks = builder(*args)
        json_str = _import_json().dumps(blocks)
        assert json_str is not None
        assert len(json_str) > 0


def parse_flags(text: str):
    import re
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


class TestParseFlags:
    def test_no_flags(self):
        q, s, sv = parse_flags("what caused the 5xx spike?")
        assert q == "what caused the 5xx spike?"
        assert s == ""
        assert sv == ""

    def test_since_flag(self):
        q, s, sv = parse_flags("--since 3h what caused the spike?")
        assert q == "what caused the spike?"
        assert s == "3h"
        assert sv == ""

    def test_service_flag(self):
        q, s, sv = parse_flags("--service checkout what happened?")
        assert q == "what happened?"
        assert sv == "checkout"

    def test_both_flags(self):
        q, s, sv = parse_flags("--since 2h --service checkout any ideas?")
        assert q == "any ideas?"
        assert s == "2h"
        assert sv == "checkout"


class TestSanitizeMrkdwn:
    def test_strips_channel(self):
        assert _sanitize_mrkdwn("hit <!channel>") == "hit [channel]"

    def test_strips_everyone(self):
        assert _sanitize_mrkdwn("ping <!everyone>") == "ping [everyone]"

    def test_strips_here(self):
        assert _sanitize_mrkdwn("attention <!here>") == "attention [here]"

    def test_passes_clean_text(self):
        assert _sanitize_mrkdwn("hello world") == "hello world"


def test_truncate_long_section_text():
    long_text = "A" * 3500
    report = {
        "summary": long_text,
        "evidence_chain": [],
        "people_involved": [],
        "suggested_actions": [],
        "sources": {},
        "errors": {},
        "confidence": "Low",
        "timestamp": "",
    }
    blocks = investigation_report(report)
    blocks_str = str(blocks)
    assert len(blocks_str) < 4500
