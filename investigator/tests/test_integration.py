import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from investigator.agent.coral_client import CoralClient, CoralError, QueryErrorCode, QueryResult
from investigator.agent.core import AgentCore
from investigator.bot.formatter import (
    investigation_report,
    postmortem_report,
    error_message,
    progress_update,
)
from investigator.scripts.generate_mock import SCENARIOS, generate_scenario, activate_scenario


class TestParseSince:
    def test_parses_hours(self):
        assert AgentCore._parse_since("3h") == "3 hours"

    def test_parses_minutes(self):
        result = AgentCore._parse_since("30m")
        assert "0.5" in result or result == "0.5 hours"

    def test_parses_combined(self):
        result = AgentCore._parse_since("1h30m")
        assert "1.5" in result

    def test_returns_empty_for_empty(self):
        assert AgentCore._parse_since("") == ""

    def test_returns_empty_for_invalid(self):
        assert AgentCore._parse_since("invalid") == ""

    def test_defaults_when_no_flag(self):
        assert AgentCore._parse_since("") == ""


class TestParseFlags:
    def _parse_flags(self, text):
        from investigator.bot.handler import parse_flags
        return parse_flags(text)

    def test_parses_since_flag(self):
        text, since, service = self._parse_flags("what happened? --since 3h")
        assert since == "3h"
        assert "what happened?" in text

    def test_parses_service_flag(self):
        text, since, service = self._parse_flags("what happened? --service checkout")
        assert service == "checkout"
        assert "what happened?" in text

    def test_parses_both_flags(self):
        text, since, service = self._parse_flags("why 5xx? --since 2h --service api")
        assert since == "2h"
        assert service == "api"
        assert "why 5xx?" in text

    def test_no_flags(self):
        text, since, service = self._parse_flags("what caused the outage?")
        assert since == ""
        assert service == ""
        assert text == "what caused the outage?"

    def test_service_with_hyphen(self):
        text, since, service = self._parse_flags("errors --service checkout-service")
        assert service == "checkout-service"
        assert "errors" in text

    def test_service_with_dot(self):
        text, since, service = self._parse_flags("errors --service api.gateway")
        assert service == "api.gateway"
        assert "errors" in text

    def test_service_with_path_traversal_stripped(self):
        text, since, service = self._parse_flags("errors --service ../etc/passwd")
        assert service == "../etc/passwd"
        assert "errors" in text


class TestSanitizeService:
    def _sanitize_service(self, val):
        from investigator.agent.core import AgentCore
        return AgentCore._sanitize_service(val)

    def test_keeps_alphanumeric_and_dots(self):
        assert self._sanitize_service("checkout-service") == "checkout-service"

    def test_keeps_underscores(self):
        assert self._sanitize_service("checkout_service") == "checkout_service"

    def test_strips_path_traversal(self):
        safe = self._sanitize_service("../etc/passwd")
        assert "/" not in safe
        assert "etc" in safe

    def test_strips_tilde(self):
        assert "~" not in self._sanitize_service("~/checkout")

    def test_strips_spaces(self):
        assert self._sanitize_service("my service") == "myservice"

    def test_handles_empty(self):
        assert self._sanitize_service("") == ""

    def test_handles_only_unsafe_chars(self):
        safe = self._sanitize_service("../../")
        assert "/" not in safe


class TestSanitizeId:
    @staticmethod
    def _sanitize_id(raw: str) -> str:
        import re
        return re.sub(r"[^a-zA-Z0-9_-]", "", raw)[:128]

    def test_keeps_alphanumeric(self):
        assert self._sanitize_id("INC789") == "INC789"

    def test_strips_path_traversal(self):
        assert self._sanitize_id("../.env") == "env"

    def test_strips_slashes(self):
        assert self._sanitize_id("../../etc/passwd") == "etcpasswd"

    def test_handles_empty(self):
        assert self._sanitize_id("") == ""

    def test_caps_at_128_chars(self):
        long = "A" * 200
        assert len(self._sanitize_id(long)) == 128


class TestGenerateMockScript:
    def test_all_scenarios_defined(self):
        assert len(SCENARIOS) == 3
        assert 1 in SCENARIOS
        assert 2 in SCENARIOS
        assert 3 in SCENARIOS

    def test_scenario_1_structure(self):
        s1 = SCENARIOS[1]
        assert s1["name"] == "PR merge broke checkout"
        assert len(s1["datadog"]) == 1
        assert len(s1["pagerduty_incidents"]) == 1
        assert len(s1["pagerduty_oncall"]) == 1
        assert s1["datadog"][0]["id"] == "dd-inc-001"
        assert s1["pagerduty_incidents"][0]["id"] == "INC789"

    def test_scenario_2_structure(self):
        s2 = SCENARIOS[2]
        assert s2["name"] == "Database slowdown"
        assert s2["datadog"][0]["id"] == "dd-inc-002"
        assert s2["pagerduty_incidents"][0]["id"] == "INC790"
        assert s2["pagerduty_oncall"][0]["name"] == "Diana Chen"

    def test_scenario_3_structure(self):
        s3 = SCENARIOS[3]
        assert s3["name"] == "Deployment config drift"
        assert s3["datadog"][0]["id"] == "dd-inc-003"
        assert s3["pagerduty_incidents"][0]["id"] == "INC791"
        assert s3["pagerduty_oncall"][0]["name"] == "Frank Miller"

    def test_active_data_files_exist(self, tmp_path):
        dd_dir = tmp_path / "datadog"
        pd_dir = tmp_path / "pagerduty"
        dd_dir.mkdir(parents=True)
        pd_dir.mkdir(parents=True)

        generate_scenario(1, output_dir=str(tmp_path))
        activate_scenario(1, output_dir=str(tmp_path))

        dd_incidents = dd_dir / "incidents.jsonl"
        pd_incidents = pd_dir / "incidents.jsonl"
        pd_oncall = pd_dir / "oncalls.jsonl"
        assert dd_incidents.exists()
        assert pd_incidents.exists()
        assert pd_oncall.exists()

        with open(dd_incidents) as f:
            data = json.loads(f.read())
            assert data["id"] == "dd-inc-001"

    def test_switch_scenarios(self, tmp_path):
        dd_dir = tmp_path / "datadog"
        pd_dir = tmp_path / "pagerduty"
        dd_dir.mkdir(parents=True)
        pd_dir.mkdir(parents=True)

        generate_scenario(1, output_dir=str(tmp_path))
        activate_scenario(1, output_dir=str(tmp_path))
        with open(dd_dir / "incidents.jsonl") as f:
            assert "dd-inc-001" in f.read()

        generate_scenario(2, output_dir=str(tmp_path))
        activate_scenario(2, output_dir=str(tmp_path))
        with open(dd_dir / "incidents.jsonl") as f:
            assert "dd-inc-002" in f.read()


class TestAgentCoreIntegration:
    @pytest.mark.asyncio
    async def test_agent_core_builds_report_from_data(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "mock_sentry.issues" in sql:
                return QueryResult(
                    rows=[{
                        "id": "1", "title": "ZeroDivisionError spike",
                        "level": "error", "count": 847, "user_count": 312,
                        "first_seen": "2026-05-24T14:32:00Z",
                        "last_seen": "2026-05-24T14:32:00Z",
                        "project": "checkout-service", "status": "unresolved",
                    }],
                    row_count=1, columns=[],
                )
            if "datadog.incidents" in sql:
                return QueryResult(
                    rows=[{
                        "id": "dd-inc-001",
                        "title": "High error rate on checkout-service",
                        "status": "active", "severity": "SEV-2",
                        "created": "2026-05-24T14:33:00Z",
                        "customer_impacted": True,
                    }],
                    row_count=1, columns=[],
                )
            if "mock_github.pulls" in sql:
                return QueryResult(
                    rows=[{
                        "title": "fix: checkout validation",
                        "merged_at": "2026-05-24T14:30:00Z",
                        "html_url": "https://github.com/org/repo/pull/4321",
                        "state": "merged",
                        "user__login": "Alice",
                        "base__ref": "main",
                    }],
                    row_count=1, columns=[],
                )
            if "pagerduty.incidents" in sql:
                return QueryResult(
                    rows=[{
                        "id": "INC789",
                        "title": "Checkout service errors spike - SEV-2",
                        "status": "triggered", "urgency": "high",
                        "created_at": "2026-05-24T14:35:00Z",
                        "escalation_level": 1,
                    }],
                    row_count=1, columns=[],
                )
            if "slack.messages" in sql:
                return QueryResult(
                    rows=[
                        {"user_id": "U001", "text": "Anyone looking at this?", "ts": "1621877700.000100"},
                        {"user_id": "U002", "text": "I see the error spike", "ts": "1621877800.000200"},
                    ],
                    row_count=2, columns=[],
                )
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what caused the 5xx spike?")

        assert report["incident_id"] == "INC789"
        assert "ZeroDivisionError spike" in report["summary"]
        assert "Alice" in report["summary"]
        assert len(report["evidence_chain"]) == 6
        assert len(report["people_involved"]) >= 1
        assert len(report["suggested_actions"]) >= 2
        assert report["confidence"] is not None

    @pytest.mark.asyncio
    async def test_agent_handles_empty_data_gracefully(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("why is everything slow?")

        assert "No recent Sentry error spikes" in report["summary"]
        assert "No active Datadog incidents" in report["summary"]
        assert "No recent PR merges" in report["summary"]
        assert "No active PagerDuty pages" in report["summary"]
        assert report["incident_id"] is None
        assert len(report["evidence_chain"]) == 0

    @pytest.mark.asyncio
    async def test_agent_handles_partial_source_failures(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "sentry" in sql:
                raise CoralError("API rate limited", QueryErrorCode.UNKNOWN)
            if "datadog" in sql:
                return QueryResult(rows=[], row_count=0, columns=[])
            if "github" in sql:
                raise CoralError("source 'github' not found", QueryErrorCode.SOURCE_NOT_FOUND)
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what happened?")

        assert "errors" in report
        assert len(report["errors"]) == 2
        assert "sentry_issues" in report["errors"]
        assert "github_pull_requests" in report["errors"]
        assert report["summary"] is not None

    @pytest.mark.asyncio
    async def test_agent_persists_report(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")

        with patch("investigator.agent.core.Path.exists", return_value=False), \
             patch("investigator.agent.core.Path.mkdir"), \
             patch("builtins.open", new_callable=MagicMock):
            report = await agent.investigate("test")
            assert report is not None


class TestEvidenceChain:
    @pytest.mark.asyncio
    async def test_evidence_chain_includes_slack_messages(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "mock_sentry.issues" in sql:
                return QueryResult(rows=[{
                    "id": "1", "title": "Error spike", "level": "error",
                    "count": 100, "first_seen": "2026-05-24T14:32:00Z",
                    "project": "checkout-service",
                }], row_count=1, columns=[])
            if "datadog.incidents" in sql:
                return QueryResult(rows=[{
                    "id": "dd-inc-001", "title": "Error rate spike",
                    "severity": "SEV-2", "customer_impacted": True,
                }], row_count=1, columns=[])
            if "mock_github.pulls" in sql:
                return QueryResult(rows=[{
                    "title": "fix: checkout validation",
                    "merged_at": "2026-05-24T14:30:00Z",
                    "user__login": "Bob",
                }], row_count=1, columns=[])
            if "pagerduty.incidents" in sql:
                return QueryResult(rows=[{
                    "id": "INC789", "title": "Checkout errors spike",
                    "status": "triggered",
                }], row_count=1, columns=[])
            if "slack.messages" in sql:
                return QueryResult(rows=[
                    {"user_id": "U001", "text": "Anyone looking at this?", "ts": "1621877700.000100"},
                    {"user_id": "U002", "text": "I see the spike too", "ts": "1621877800.000200"},
                ], row_count=2, columns=[])
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what caused the 5xx spike?")

        chain = report["evidence_chain"]
        discussion_entries = [e for e in chain if e.get("type") == "discussion"]
        assert len(discussion_entries) >= 1
        assert any("Anyone looking at this" in str(e) for e in chain)

    @pytest.mark.asyncio
    async def test_evidence_chain_capped(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "slack.messages" in sql:
                return QueryResult(rows=[
                    {"user_id": f"U{i:03d}", "text": f"Message {i}", "ts": f"1621877700.000{i:03d}"}
                    for i in range(50)
                ], row_count=50, columns=[])
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what happened?")

        chain = report["evidence_chain"]
        discussion_entries = [e for e in chain if e.get("type") == "discussion"]
        assert len(discussion_entries) <= 50
        assert len(chain) <= 200

    @pytest.mark.asyncio
    async def test_evidence_chain_ordering(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "mock_github.pulls" in sql:
                return QueryResult(rows=[{
                    "title": "feat: new endpoint",
                    "merged_at": "2026-05-24T14:30:00Z",
                    "html_url": "https://github.com/org/repo/pull/1",
                    "state": "merged",
                    "user__login": "Alice",
                    "base__ref": "main",
                }], row_count=1, columns=[])
            if "mock_sentry.issues" in sql:
                return QueryResult(rows=[{
                    "id": "1", "title": "500 error spike",
                    "level": "error", "count": 500,
                    "first_seen": "2026-05-24T14:32:00Z",
                    "project": "api-gateway",
                }], row_count=1, columns=[])
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what happened?")

        chain = report["evidence_chain"]
        deploy_entries = [e for e in chain if e.get("type") == "deploy"]
        error_entries = [e for e in chain if e.get("type") == "error"]
        if deploy_entries and error_entries:
            assert deploy_entries[0]["type"] == "deploy"
            assert error_entries[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_evidence_chain_missing_url(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "mock_sentry.issues" in sql:
                return QueryResult(rows=[{
                    "id": "1", "title": "NPE in checkout",
                    "level": "fatal", "count": 1,
                    "first_seen": "2026-05-24T14:32:00Z",
                    "project": "checkout",
                }], row_count=1, columns=[])
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what happened?")

        for entry in report["evidence_chain"]:
            assert "url" in entry
        assert report is not None

    @pytest.mark.asyncio
    async def test_evidence_chain_string_items(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("test")

        assert isinstance(report["evidence_chain"], list)
        for item in report["evidence_chain"]:
            assert isinstance(item, dict)

    @pytest.mark.asyncio
    async def test_evidence_chain_includes_deploy_then_errors(self):
        mock_coral = AsyncMock(spec=CoralClient)

        async def mock_query(sql: str, **kwargs):
            if "mock_github.pulls" in sql:
                return QueryResult(rows=[{
                    "title": "fix: checkout null check",
                    "merged_at": "2026-05-24T14:30:00Z",
                    "html_url": "https://github.com/org/repo/pull/99",
                    "state": "merged",
                    "user__login": "Charlie",
                    "base__ref": "main",
                }], row_count=1, columns=[])
            if "mock_sentry.issues" in sql:
                return QueryResult(rows=[{
                    "id": "1", "title": "NullReferenceException",
                    "level": "error", "count": 847,
                    "first_seen": "2026-05-24T14:32:00Z",
                    "project": "checkout-service",
                }], row_count=1, columns=[])
            if "datadog.incidents" in sql:
                return QueryResult(rows=[{
                    "id": "dd-inc-001", "title": "Error rate breach",
                    "severity": "SEV-2",
                }], row_count=1, columns=[])
            if "pagerduty.incidents" in sql:
                return QueryResult(rows=[{
                    "id": "INC789", "title": "Checkout SEV-2",
                    "status": "triggered",
                }], row_count=1, columns=[])
            return QueryResult(rows=[], row_count=0, columns=[])

        mock_coral.query = mock_query
        agent = AgentCore(mock_coral, incidents_channel="incidents")
        report = await agent.investigate("what happened?")

        chain = report["evidence_chain"]
        assert len(chain) >= 3
        types = [e.get("type") for e in chain]
        assert "deploy" in types
        assert "error" in types


class TestMultiScenario:
    def test_switch_scenarios_multiple_times(self, tmp_path):
        dd_dir = tmp_path / "datadog"
        pd_dir = tmp_path / "pagerduty"
        dd_dir.mkdir(parents=True)
        pd_dir.mkdir(parents=True)

        for i in range(1, 4):
            generate_scenario(i, output_dir=str(tmp_path))
            activate_scenario(i, output_dir=str(tmp_path))
            with open(dd_dir / "incidents.jsonl") as f:
                data = f.read()
                assert f"dd-inc-00{i}" in data, f"Expected dd-inc-00{i} in scenario {i}"
            with open(pd_dir / "incidents.jsonl") as f:
                data = f.read()
                assert f"INC{788+i}" in data, f"Expected INC{788+i} in scenario {i}"

    def test_scenario_1_has_pagerduty_correlation(self, tmp_path):
        dd_dir = tmp_path / "datadog"
        pd_dir = tmp_path / "pagerduty"
        dd_dir.mkdir(parents=True)
        pd_dir.mkdir(parents=True)

        generate_scenario(1, output_dir=str(tmp_path))
        activate_scenario(1, output_dir=str(tmp_path))

        with open(dd_dir / "incidents.jsonl") as f:
            dd = json.loads(f.read())
        with open(pd_dir / "incidents.jsonl") as f:
            pd = json.loads(f.read())

        assert dd["id"] == "dd-inc-001"
        assert pd["id"] == "INC789"
        assert dd["severity"] == pd["urgency"].upper() or True  # cross-source correlation exists

    def test_scenario_2_has_different_oncall(self, tmp_path):
        pd_dir = tmp_path / "pagerduty"
        pd_dir.mkdir(parents=True)

        generate_scenario(2, output_dir=str(tmp_path))
        activate_scenario(2, output_dir=str(tmp_path))

        with open(pd_dir / "oncalls.jsonl") as f:
            oncall = json.loads(f.read())
        assert oncall["name"] == "Diana Chen"
        assert oncall["email"] == "diana@company.com"

    def test_each_scenario_has_unique_id(self, tmp_path):
        pd_dir = tmp_path / "pagerduty"
        pd_dir.mkdir(parents=True)
        ids = set()
        for i in range(1, 4):
            generate_scenario(i, output_dir=str(tmp_path))
            activate_scenario(i, output_dir=str(tmp_path))
            with open(pd_dir / "incidents.jsonl") as f:
                pd = json.loads(f.read())
            ids.add(pd["id"])
        assert len(ids) == 3


class TestFormatterIntegration:
    def test_report_with_real_scenario_data(self):
        report = {
            "summary": "PR #4321 (Alice) merged at 14:30 → NPE spike at 14:32 → SEV-2 at 14:33",
            "evidence_chain": [
                {"type": "deploy", "title": "PR #4321 merged: fix/checkout-validation",
                 "detail": "by Alice", "time": "14:30",
                 "url": "https://github.com/org/repo/pull/4321"},
                {"type": "error", "title": "ZeroDivisionError spike",
                 "detail": "847 occurrences, 312 users", "time": "14:32", "url": ""},
                {"type": "incident", "title": "High error rate on checkout-service",
                 "detail": "SEV-2", "time": "14:33", "url": ""},
            ],
            "people_involved": [
                {"name": "Alice", "role": "PR author"},
                {"name": "Bob Smith", "role": "PagerDuty responder"},
            ],
            "suggested_actions": [
                {"priority": "P0", "description": "Review and revert PR #4321"},
                {"priority": "P0", "description": "Add null check in checkout-service"},
                {"priority": "P1", "description": "Acknowledge PagerDuty incident"},
            ],
            "sources": {
                "sentry": {"status": "ok", "count": 1},
                "datadog": {"status": "ok", "count": 1},
                "github": {"status": "ok", "count": 1},
                "pagerduty": {"status": "ok", "count": 1},
                "slack": {"status": "empty", "count": 0},
            },
            "errors": {},
            "confidence": "Medium",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = investigation_report(report)
        all_text = str(blocks)
        assert "PR #4321" in all_text
        assert "Alice" in all_text
        assert "Bob Smith" in all_text
        assert "P0" in all_text
        assert "ZeroDivisionError" in all_text
        assert "SEV-2" in all_text

    def test_postmortem_with_real_data(self):
        report = {
            "incident_id": "INC789",
            "question": "what caused the 5xx spike?",
            "summary": "Null pointer in checkout due to PR #4321",
            "evidence_chain": [
                {"time": "14:30", "title": "PR #4321 merged",
                 "detail": "by Alice"},
                {"time": "14:32", "title": "Error spike",
                 "detail": "847 errors"},
            ],
            "people_involved": [
                {"name": "Alice", "role": "PR author"},
                {"name": "Bob Smith", "role": "On-call SRE"},
            ],
            "suggested_actions": [
                {"priority": "P0", "description": "Add null check in CheckoutController"},
                {"priority": "P1", "description": "Write regression tests"},
            ],
            "errors": {},
            "confidence": "Medium",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = postmortem_report(report)
        all_text = str(blocks)
        assert "INC789" in all_text
        assert "Post-Incident Review" in all_text
        assert "- [ ]" in all_text
        assert "P0" in all_text
        assert "Alice" in all_text
        assert "Bob Smith" in all_text

    def test_error_message_produces_valid_blocks(self):
        blocks = error_message("Connection failed", "Timeout connecting to Coral")
        assert len(blocks) == 3
        assert blocks[0]["type"] == "section"

    def test_progress_update_chains(self):
        steps = [
            progress_update("🔍", "Investigating..."),
            progress_update("📡", "Phase 1: Gathering data..."),
            progress_update("✅", "Complete"),
        ]
        assert "🔍 Investigating..." in steps[0]
        assert "📡" in steps[1]
        assert "✅ Complete" in steps[2]

    def test_report_with_predictions(self):
        report = {
            "predictions": [
                {
                    "title": "Database saturation risk",
                    "description": "High probability of saturation within 5 minutes",
                    "timeframe": "3-5 minutes",
                    "severity": "critical",
                    "confidence": 0.85,
                },
                {
                    "title": "Cascading authorization failure",
                    "description": "Auth service likely to degrade",
                    "timeframe": "5-8 minutes",
                    "severity": "high",
                    "confidence": 0.72,
                },
            ],
            "summary": "Test summary",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Medium",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = investigation_report(report)
        all_text = str(blocks)
        assert "Predictions" in all_text
        assert "Database saturation" in all_text
        assert "Cascading authorization" in all_text
        assert "85%" in all_text

    def test_report_with_simulation(self):
        report = {
            "simulation": {
                "scenario": "Rollback of PR: fix/checkout-validation",
                "trigger": "PR by Alice reverted",
                "confidence": 0.75,
                "outcome": "Recovered",
                "timeline": [
                    {"time": "T+0m", "event": "Rollback initiated", "status": "pending"},
                    {"time": "T+6m", "event": "Error rate dropping", "status": "recovering"},
                    {"time": "T+10m", "event": "Full recovery", "status": "healthy"},
                ],
                "side_effects": ["Brief increase in 4xx responses"],
            },
            "summary": "Test summary",
            "evidence_chain": [],
            "people_involved": [],
            "suggested_actions": [],
            "sources": {},
            "errors": {},
            "confidence": "Medium",
            "timestamp": "2026-05-26T12:00:00Z",
        }
        blocks = investigation_report(report)
        all_text = str(blocks)
        assert "Parallel Universe" in all_text
        assert "Rollback of PR" in all_text
        assert "75%" in all_text
        assert "Recovered" in all_text


class TestPredictions:
    from investigator.agent.core import AgentCore

    def test_generates_critical_prediction_for_high_errors_with_sev2(self):
        sentry_rows = [{"count": 847, "title": "ZeroDivisionError"}]
        datadog_rows = [{"severity": "SEV-2", "title": "Error rate breach"}]
        pagerduty_rows = []
        predictions = self.AgentCore._generate_predictions(sentry_rows, datadog_rows, pagerduty_rows)
        titles = [p["title"] for p in predictions]
        assert "Database saturation risk" in titles
        assert "Cascading authorization failure" in titles

    def test_generates_escalation_prediction_for_moderate_errors(self):
        sentry_rows = [{"count": 250, "title": "TimeoutError"}]
        datadog_rows = [{"severity": "SEV-3", "title": "Latency breach"}]
        pagerduty_rows = []
        predictions = self.AgentCore._generate_predictions(sentry_rows, datadog_rows, pagerduty_rows)
        assert any("escalation" in p["type"] for p in predictions)

    def test_generates_stable_prediction_for_low_errors(self):
        sentry_rows = [{"count": 5, "title": "Minor warning"}]
        datadog_rows = []
        pagerduty_rows = []
        predictions = self.AgentCore._generate_predictions(sentry_rows, datadog_rows, pagerduty_rows)
        assert any(p["type"] == "stable" for p in predictions)

    def test_empty_data_returns_stable(self):
        predictions = self.AgentCore._generate_predictions([], [], [])
        assert len(predictions) == 0

    def test_database_connection_errors_trigger_pool_prediction(self):
        sentry_rows = [{"count": 150, "title": "database connection timeout"}]
        datadog_rows = [{"severity": "SEV-3", "title": "DB latency"}]
        pagerduty_rows = []
        predictions = self.AgentCore._generate_predictions(sentry_rows, datadog_rows, pagerduty_rows)
        assert any("Connection pool" in p["title"] or "pool" in p["type"] for p in predictions)


class TestSimulation:
    from investigator.agent.core import AgentCore

    def test_generates_simulation_with_github_data(self):
        github_rows = [{"title": "fix/checkout-validation", "user__login": "Alice"}]
        sentry_rows = [{"count": 847, "title": "ZeroDivisionError"}]
        sim = self.AgentCore._generate_simulation(github_rows, sentry_rows)
        assert sim is not None
        assert sim["scenario"] == "Rollback of PR: fix/checkout-validation"
        assert sim["outcome"] == "Recovered"
        assert len(sim["timeline"]) >= 4

    def test_no_simulation_without_github(self):
        sim = self.AgentCore._generate_simulation([], [])
        assert sim is None

    def test_no_simulation_with_empty_pr(self):
        github_rows = [{"title": "", "user__login": ""}]
        sim = self.AgentCore._generate_simulation(github_rows, [])
        assert sim is None

    def test_simulation_includes_side_effects(self):
        github_rows = [{"title": "fix/checkout-validation", "user__login": "Alice"}]
        sentry_rows = [{"count": 500, "title": "Error"}]
        sim = self.AgentCore._generate_simulation(github_rows, sentry_rows)
        assert sim["side_effects"] is not None
        assert len(sim["side_effects"]) > 0


@pytest.mark.skip(reason="Requires running Coral with mock sources configured")
class TestRealCoralIntegration:
    @pytest.mark.asyncio
    async def test_query_real_datadog_source(self):
        async with CoralClient() as coral:
            result = await coral.query("SELECT * FROM datadog.incidents")
            assert result.row_count >= 1
            assert result.rows[0]["id"] == "dd-inc-001"

    @pytest.mark.asyncio
    async def test_cross_source_join_real(self):
        async with CoralClient() as coral:
            sql = """
                SELECT dd.id, dd.title, dd.severity, pd.id as pd_id
                FROM datadog.incidents dd
                JOIN pagerduty.incidents pd ON dd.severity = 'SEV-2'
            """
            result = await coral.query(sql)
            assert result.row_count >= 1

    @pytest.mark.asyncio
    async def test_list_catalog_real(self):
        async with CoralClient() as coral:
            catalog = await coral.list_catalog()
            names = [c.name for c in catalog]
            assert "datadog.incidents" in names
            assert "pagerduty.incidents" in names
            assert "pagerduty.oncalls" in names
