import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from investigator.agent.coral_client import CoralClient, CoralError, QueryErrorCode
from investigator.agent.reasoning import ReasoningEngine

_GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "").strip()
_GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
_USE_MOCK = os.environ.get("USE_MOCK_SOURCES", "true").strip().lower() == "true"

logger = logging.getLogger(__name__)


class SourceStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class SourceHealth:
    source_name: str
    status: SourceStatus = SourceStatus.OK
    error_count: int = 0
    last_error: Optional[str] = None
    last_error_code: Optional[str] = None
    retries_used: int = 0
    fallback_used: bool = False

    def record_success(self):
        self.status = SourceStatus.OK

    def record_error(self, error: CoralError):
        self.error_count += 1
        self.last_error = str(error)[:500]
        self.last_error_code = error.code.value if hasattr(error.code, 'value') else str(error.code)
        if self.error_count >= 3 or error.code in (
            QueryErrorCode.SOURCE_NOT_FOUND,
            QueryErrorCode.TABLE_NOT_FOUND,
        ):
            self.status = SourceStatus.FAILED
        else:
            self.status = SourceStatus.DEGRADED

    def record_retry(self):
        self.retries_used += 1

    def record_fallback(self):
        self.fallback_used = True
        self.status = SourceStatus.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "count": 0,
            "error": self.last_error,
            "error_code": self.last_error_code,
            "retries": self.retries_used,
            "fallback": self.fallback_used,
        }


_HTML_TAG_RE = re.compile(r"<[^>]*>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)


def _strip_html(text: str) -> str:
    text = _SCRIPT_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    return text


_INTERNAL_PATTERNS = [
    "Traceback (most recent call last)",
    "File \"",
    "at ",
    "InternalError",
    "panic",
    "stack trace",
]


def _is_internal_error(msg: str) -> bool:
    return any(p.lower() in msg.lower() for p in _INTERNAL_PATTERNS)


class AgentCore:
    @staticmethod
    def _source(table: str) -> str:
        prefix = "mock_" if _USE_MOCK else ""
        bundled = {"sentry.issues", "github.pulls", "slack.messages"}
        if _USE_MOCK and table in bundled:
            return f"{prefix}{table}"
        return table

    PHASE1_SINCE_DEFAULTS = {
        "sentry_issues": "2 hours",
        "datadog_incidents": "",
        "github_pull_requests": "4 hours",
        "pagerduty_incidents": "",
        "slack_messages": "2 hours",
    }

    PHASE1_QUERY_TEMPLATES = {
        "sentry_issues": """
            SELECT id, title, level, count, user_count,
                   first_seen, last_seen, project, status
            FROM {sentry_issues}
            WHERE last_seen >= CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}'
              AND level IN ('error', 'fatal')
              {{SERVICE_FILTER}}
            ORDER BY count DESC
            LIMIT 20
        """,
        "datadog_incidents": """
            SELECT id, title, status, severity, created,
                   customer_impacted, resolved_at
            FROM {datadog_incidents}
            WHERE status = 'active'
            ORDER BY created DESC
        """,
        "github_pull_requests": """
            SELECT title, merged_at, html_url, state,
                   user__login, base__ref, head__label
            FROM {github_pulls}
            WHERE state = 'merged'
              AND merged_at >= CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}'
            ORDER BY merged_at DESC
            LIMIT 10
        """,
        "pagerduty_incidents": """
            SELECT id, title, status, urgency, created_at, escalation_level
            FROM {pagerduty_incidents}
            WHERE status = 'triggered'
            ORDER BY urgency DESC
        """,
        "slack_messages": """
            SELECT user_id, text, ts, channel, permalink
            FROM {slack_messages}
            WHERE channel = '{{INCIDENTS_CHANNEL}}'
              AND ts >= CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}'
            ORDER BY ts DESC
            LIMIT 30
        """,
    }

    def __init__(self, coral: CoralClient, incidents_channel: str = "incidents"):
        self._coral = coral
        self._incidents_channel = incidents_channel
        self._iteration_count = 0
        self._max_loops = 2
        self._reasoning: Optional[ReasoningEngine] = None
        self._source_health: dict[str, SourceHealth] = {}
        self._phase2_health: dict[str, int] = {"total_queries": 0, "failed_queries": 0, "retries_used": 0, "fallbacks_used": 0}

    async def investigate(self, question: str) -> dict[str, Any]:
        phase1_data = await self._run_phase1()
        report = self._build_report(question, phase1_data)
        await self._persist_report(report)
        return report

    async def investigate_with_reasoning(
        self, question: str, max_loops: int = 2,
        on_progress: Optional[callable] = None,
        on_phase2_query: Optional[callable] = None,
        since: str = "", service: str = "",
    ) -> dict[str, Any]:
        if on_progress:
            await on_progress("📡", "Phase 1: Gathering data from 5 sources...")
        phase1_data = await self._run_phase1(since=since, service=service)
        if on_progress:
            await on_progress("🧠", "Analyzing initial signals...")
        reasoning = self._get_reasoning()
        llm_result = await reasoning.analyze_with_loop(
            question=question,
            phase1_data=phase1_data,
            coral_query_fn=self._coral.query,
            max_loops=max_loops,
            incidents_channel=self._incidents_channel,
            on_phase2_start=lambda: on_progress(
                "🔬", "Phase 2: Running follow-up queries..."
            ) if on_progress else None,
            on_query=on_phase2_query,
        )
        if on_progress:
            await on_progress("✅", "Investigation complete. Generating report...")
        report = self._merge_llm_into_report(question, phase1_data, llm_result)
        await self._persist_report(report)
        return report

    def _get_reasoning(self) -> ReasoningEngine:
        if self._reasoning is None:
            self._reasoning = ReasoningEngine()
        return self._reasoning

    def _merge_llm_into_report(
        self,
        question: str,
        phase1: dict[str, Any],
        llm_result: dict[str, Any],
    ) -> dict[str, Any]:
        base = self._build_report(question, phase1, llm_result=llm_result)
        base["root_cause"] = llm_result.get("root_cause", base.get("root_cause", ""))
        base["analysis"] = llm_result.get("analysis", "")
        base["timeline"] = llm_result.get("timeline", base.get("evidence_chain", []))
        base["confidence"] = llm_result.get("confidence", base.get("confidence", "Medium"))
        if llm_result.get("suggested_actions"):
            base["suggested_actions"] = llm_result["suggested_actions"]
        base["phase2_run"] = True
        base["phase2_health"] = dict(self._phase2_health)
        return base

    @staticmethod
    def _sanitize_service(service: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "", service)
        if cleaned != service:
            logger.warning("Service name contained unsafe characters: %r", service)
        return cleaned

    @staticmethod
    def _parse_since(raw: str) -> str:
        if not raw:
            return ""
        total_hours = 0
        for match in re.finditer(r"(\d+)\s*h", raw):
            total_hours += int(match.group(1))
        for match in re.finditer(r"(\d+)\s*m(?!i)", raw):
            total_hours += int(match.group(1)) / 60
        if total_hours <= 0:
            return ""
        label = "hour" if total_hours == 1 else "hours"
        return f"{total_hours} {label}"

    async def _run_phase1(
        self, since: str = "", service: str = "",
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        parsed_since = self._parse_since(since)
        safe_service = self._sanitize_service(service) if service else ""
        source_table_map = {
            "sentry_issues": self._source("sentry.issues"),
            "datadog_incidents": self._source("datadog.incidents"),
            "github_pull_requests": self._source("github.pulls"),
            "pagerduty_incidents": self._source("pagerduty.incidents"),
            "slack_messages": self._source("slack.messages"),
        }
        self._source_health: dict[str, SourceHealth] = {}
        for source_name, template in self.PHASE1_QUERY_TEMPLATES.items():
            health = SourceHealth(source_name=source_name)
            self._source_health[source_name] = health
            since_val = parsed_since or self.PHASE1_SINCE_DEFAULTS.get(source_name, "")
            query_params: dict[str, str] = {}
            service_filter = ""
            if source_name == "sentry_issues" and safe_service:
                service_filter = "AND project = $service"
                query_params["service"] = safe_service
            query = (
                template
                .replace("{sentry_issues}", source_table_map["sentry_issues"])
                .replace("{datadog_incidents}", source_table_map["datadog_incidents"])
                .replace("{github_pulls}", source_table_map["github_pull_requests"])
                .replace("{pagerduty_incidents}", source_table_map["pagerduty_incidents"])
                .replace("{slack_messages}", source_table_map["slack_messages"])
                .replace("{{INCIDENTS_CHANNEL}}", self._incidents_channel)
                .replace("{{SINCE}}", since_val)
                .replace("{{SERVICE_FILTER}}", service_filter)
            )
            try:
                result = await self._coral.query(query, params=query_params if query_params else None)
                health.record_success()
                data[source_name] = {
                    "rows": result.rows,
                    "row_count": result.row_count,
                    "columns": result.columns,
                }
                logger.info(
                    "Phase 1 [%s]: %d rows returned",
                    source_name,
                    result.row_count,
                )
            except CoralError as e:
                health.record_error(e)
                logger.warning("Phase 1 [%s] failed: %s", source_name, e)
                err_msg = str(e)[:500] if not _is_internal_error(str(e)) else "Internal Coral error"
                data[source_name] = {
                    "rows": [],
                    "row_count": 0,
                    "columns": [],
                    "error": err_msg,
                    "error_code": health.last_error_code,
                }
            except Exception as e:
                health.record_error(CoralError(str(e), QueryErrorCode.UNKNOWN))
                logger.error("Phase 1 [%s] unexpected error: %s", source_name, e)
                data[source_name] = {
                    "rows": [],
                    "row_count": 0,
                    "columns": [],
                    "error": "Unexpected source error",
                }
        return data

    def _build_report(
        self, question: str, phase1: dict[str, Any],
        llm_result: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        sentry = phase1.get("sentry_issues", {})
        datadog = phase1.get("datadog_incidents", {})
        github = phase1.get("github_pull_requests", {})
        pagerduty = phase1.get("pagerduty_incidents", {})
        slack_msgs = phase1.get("slack_messages", {})

        health_map = {
            "sentry": self._source_health.get("sentry_issues"),
            "datadog": self._source_health.get("datadog_incidents"),
            "github": self._source_health.get("github_pull_requests"),
            "pagerduty": self._source_health.get("pagerduty_incidents"),
            "slack": self._source_health.get("slack_messages"),
        }

        sentry_rows = sentry.get("rows", [])
        datadog_rows = datadog.get("rows", [])
        github_rows = github.get("rows", [])
        pagerduty_rows = pagerduty.get("rows", [])
        slack_rows = slack_msgs.get("rows", [])

        summary_parts = []
        incident_id = None
        if sentry_rows:
            top_error = sentry_rows[0]
            count = top_error.get("count", "?")
            summary_parts.append(
                f"{len(sentry_rows)} error group(s) found, "
                f"top: '{top_error.get('title', 'unknown')}' ({count} occurrences)"
            )
        else:
            summary_parts.append("No recent Sentry error spikes detected")

        if datadog_rows:
            dd = datadog_rows[0]
            summary_parts.append(
                f"Active {dd.get('severity', 'incident')}: '{dd.get('title', '')}'"
            )
        else:
            summary_parts.append("No active Datadog incidents")

        if github_rows:
            pr = github_rows[0]
            summary_parts.append(
                f"Recent deploy: PR by {pr.get('user__login', 'unknown')} "
                f"merged at {pr.get('merged_at', '?')}"
            )
        else:
            summary_parts.append("No recent PR merges in last 4 hours")

        if pagerduty_rows:
            pd = pagerduty_rows[0]
            incident_id = pd.get("id")
            summary_parts.append(
                f"Active PagerDuty: {pd.get('urgency', '')} urgency - '{pd.get('title', '')}'"
            )
        else:
            summary_parts.append("No active PagerDuty pages")

        evidence_chain = self._build_evidence_chain(
            sentry_rows, datadog_rows, github_rows, pagerduty_rows, slack_rows
        )
        people = self._find_people(
            github_rows, pagerduty_rows, slack_rows
        )
        predictions = self._generate_predictions(sentry_rows, datadog_rows, pagerduty_rows)
        simulation = self._generate_simulation(github_rows, sentry_rows)

        return {
            "question": question,
            "incident_id": incident_id,
            "summary": " | ".join(summary_parts),
            "evidence_chain": evidence_chain,
            "people_involved": people,
            "suggested_actions": self._suggest_actions(
                sentry_rows, datadog_rows, github_rows, pagerduty_rows
            ),
            "predictions": predictions,
            "simulation": simulation,
            "confidence": (
                llm_result.get("confidence", "Medium") if llm_result
                else "Medium (Phase 1 data correlated, no Phase 2 loop yet)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "sentry": self._build_source_dict(health_map["sentry"], sentry_rows),
                "datadog": self._build_source_dict(health_map["datadog"], datadog_rows),
                "github": self._build_source_dict(health_map["github"], github_rows),
                "pagerduty": self._build_source_dict(health_map["pagerduty"], pagerduty_rows),
                "slack": self._build_source_dict(health_map["slack"], slack_rows),
            },
            "errors": {
                s: d.get("error") for s, d in phase1.items() if "error" in d
            },
            "phase2_health": dict(self._phase2_health),
        }

    @staticmethod
    def _build_source_dict(health: Optional[SourceHealth], rows: list) -> dict[str, Any]:
        if health:
            base = health.to_dict()
            base["count"] = len(rows)
            return base
        return {
            "status": "ok" if rows else "empty",
            "count": len(rows),
            "error": None,
            "error_code": None,
            "retries": 0,
            "fallback": False,
        }

    @staticmethod
    def _build_evidence_chain(
        sentry_rows, datadog_rows, github_rows, pagerduty_rows, slack_rows,
        max_per_source: int = 20,
    ) -> list[dict[str, str]]:
        chain = []
        for pr in github_rows[:max_per_source]:
            chain.append({
                "type": "deploy",
                "title": f"PR merged: {pr.get('title', '')}",
                "detail": f"by {pr.get('user__login', 'unknown')}",
                "time": pr.get("merged_at", ""),
                "url": pr.get("html_url", ""),
            })
        for err in sentry_rows[:max_per_source]:
            chain.append({
                "type": "error",
                "title": f"Error spike: {err.get('title', '')}",
                "detail": f"{err.get('count', '?')} occurrences, {err.get('user_count', '?')} users",
                "time": err.get("last_seen", ""),
                "url": "",
            })
        for dd in datadog_rows[:max_per_source]:
            chain.append({
                "type": "incident",
                "title": f"Incident: {dd.get('title', '')}",
                "detail": f"{dd.get('severity', '?')} - Customer impacted: {dd.get('customer_impacted', '?')}",
                "time": dd.get("created", ""),
                "url": "",
            })
        for pd in pagerduty_rows[:max_per_source]:
            chain.append({
                "type": "page",
                "title": f"Page: {pd.get('title', '')}",
                "detail": f"Urgency: {pd.get('urgency', '?')}",
                "time": pd.get("created_at", ""),
                "url": "",
            })
        for msg in slack_rows[:max_per_source]:
            chain.append({
                "type": "discussion",
                "title": f"Slack message from {msg.get('user_id', 'unknown')}",
                "detail": (msg.get("text", "") or "")[:120],
                "time": msg.get("ts", ""),
                "url": "",
            })
        chain.sort(key=lambda x: x.get("time", ""))
        return chain

    @staticmethod
    def _find_people(github_rows, pagerduty_rows, slack_rows) -> list[dict[str, str]]:
        people = []
        seen = set()
        for pr in github_rows:
            name = pr.get("user__login", "")
            if name and name not in seen:
                seen.add(name)
                people.append({"name": name, "role": "PR author"})
        for pd in pagerduty_rows:
            name = pd.get("name", "")
            if name and name not in seen:
                seen.add(name)
                people.append({"name": name, "role": "PagerDuty responder"})
        for msg in slack_rows:
            user = msg.get("user_id", "")
            if user and user not in seen:
                seen.add(user)
                people.append({"name": user, "role": "Slack participant"})
        return people

    @staticmethod
    def _generate_predictions(
        sentry_rows: list, datadog_rows: list, pagerduty_rows: list,
    ) -> list[dict[str, str]]:
        predictions = []
        total_errors = sum(r.get("count", 0) for r in sentry_rows if isinstance(r, dict))
        has_sev2 = any(
            r.get("severity") == "SEV-2" for r in datadog_rows if isinstance(r, dict)
        )
        has_sev3 = any(
            r.get("severity") == "SEV-3" for r in datadog_rows if isinstance(r, dict)
        )
        has_database_errors = any(
            "database" in str(r.get("title", "")).lower()
            or "connection" in str(r.get("title", "")).lower()
            or "timeout" in str(r.get("title", "")).lower()
            for r in sentry_rows if isinstance(r, dict)
        )

        if total_errors > 500 and has_sev2:
            predictions.append({
                "type": "degradation",
                "title": "Database saturation risk",
                "description": "High probability of complete database saturation within 5 minutes given current error trajectory.",
                "timeframe": "3-5 minutes",
                "severity": "critical",
                "confidence": 0.85,
            })
            predictions.append({
                "type": "cascade",
                "title": "Cascading authorization failure",
                "description": "Authorization service likely to degrade as database connections are consumed, causing cascading auth failures across dependent services.",
                "timeframe": "5-8 minutes",
                "severity": "high",
                "confidence": 0.72,
            })
        elif total_errors > 200:
            predictions.append({
                "type": "escalation",
                "title": "Incident severity escalation",
                "description": f"Error count ({total_errors}) is trending upward. Incident likely to escalate to SEV-2 within 15 minutes if unmitigated.",
                "timeframe": "10-15 minutes",
                "severity": "high",
                "confidence": 0.78,
            })

        if has_database_errors and has_sev3:
            predictions.append({
                "type": "capacity",
                "title": "Connection pool exhaustion",
                "description": "Database connection pool is under pressure. Connection timeouts indicate pool exhaustion risk within 10 minutes.",
                "timeframe": "8-12 minutes",
                "severity": "medium",
                "confidence": 0.65,
            })

        if not predictions:
            error_rate = total_errors / max(len(sentry_rows), 1)
            if error_rate > 0:
                predictions.append({
                    "type": "stable",
                    "title": "System stabilizing",
                    "description": f"Low error rate ({total_errors} total). No escalation predicted in the next 30 minutes.",
                    "timeframe": "30 minutes",
                    "severity": "low",
                    "confidence": 0.60,
                })

        return predictions

    @staticmethod
    def _generate_simulation(
        github_rows: list, sentry_rows: list,
    ) -> Optional[dict[str, Any]]:
        if not github_rows:
            return None
        pr = github_rows[0] if isinstance(github_rows[0], dict) else {}
        pr_title = pr.get("title", "")
        pr_author = pr.get("user__login", "unknown")
        if not pr_title:
            return None

        total_errors_before = sum(r.get("count", 0) for r in sentry_rows if isinstance(r, dict))
        recovered_errors = int(total_errors_before * 0.05)

        return {
            "scenario": f"Rollback of PR: {pr_title}",
            "trigger": f"PR by {pr_author} reverted",
            "timeline": [
                {"time": "T+0m", "event": f"Rollback initiated for commit in PR '{pr_title}'", "status": "pending"},
                {"time": "T+2m", "event": "Rollback deployed to staging environment", "status": "validating"},
                {"time": "T+4m", "event": "Error rate dropping — rollback propagating through canary", "status": "recovering"},
                {"time": "T+6m", "event": f"Error rate reduced by ~{recovered_errors} — {recovered_errors} fewer errors/min", "status": "recovering"},
                {"time": "T+8m", "event": "System latency returned to baseline (< 100ms)", "status": "recovered"},
                {"time": "T+10m", "event": "Full recovery — all services operational", "status": "healthy"},
            ],
            "outcome": "Recovered",
            "confidence": 0.75,
            "side_effects": ["Brief (2 min) increase in 4xx responses during rollback propagation"],
        }

    @staticmethod
    def _suggest_actions(sentry_rows, datadog_rows, github_rows, pagerduty_rows) -> list[dict[str, str]]:
        actions = []
        if github_rows:
            pr = github_rows[0]
            actions.append({
                "priority": "P0",
                "description": f"Review and consider reverting PR #{pr.get('title', '')}",
            })
        if sentry_rows:
            err = sentry_rows[0]
            actions.append({
                "priority": "P0",
                "description": f"Investigate error: {err.get('title', '')} in {err.get('project', 'unknown')}",
            })
            actions.append({
                "priority": "P1",
                "description": "Add null check and input validation to prevent recurrence",
            })
        if pagerduty_rows:
            actions.append({
                "priority": "P1",
                "description": "Acknowledge PagerDuty incident and begin mitigation",
            })
        actions.append({
            "priority": "P2",
            "description": "Schedule post-incident review and update runbook",
        })
        return actions

    async def _persist_report(self, report: dict[str, Any]) -> None:
        import json
        from pathlib import Path

        _safe = report.copy()
        for key in ("root_cause", "analysis"):
            val = _safe.get(key)
            if isinstance(val, str):
                _safe[key] = _strip_html(val)
        timeline = _safe.get("timeline") or _safe.get("evidence_chain", [])
        if isinstance(timeline, list):
            for item in timeline:
                if isinstance(item, dict) and isinstance(item.get("title"), str):
                    item["title"] = _strip_html(item["title"])
        raw_id = _safe.get("incident_id", "unknown") or "unknown"
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", raw_id)[:128]
        reports_dir = Path(__file__).resolve().parent.parent / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"{safe_id}.json"
        try:
            with open(report_file, "w") as f:
                json.dump(_safe, f, indent=2, default=str)
            logger.info("Report saved to %s", report_file)
        except Exception as e:
            logger.warning("Failed to persist report: %s", e)
