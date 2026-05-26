import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from investigator.agent.coral_client import CoralClient, CoralError
from investigator.agent.reasoning import ReasoningEngine

logger = logging.getLogger(__name__)


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
            FROM sentry.issues
            WHERE last_seen >= CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}'
              AND level IN ('error', 'fatal')
              {{SERVICE_FILTER}}
            ORDER BY count DESC
            LIMIT 20
        """,
        "datadog_incidents": """
            SELECT id, title, status, severity, created,
                   customer_impacted, resolved_at
            FROM datadog.incidents
            WHERE status = 'active'
            ORDER BY created DESC
        """,
        "github_pull_requests": """
            SELECT title, merged_at, html_url, state,
                   user__login, base__ref, head__label
            FROM github.pull_requests
            WHERE merged_at >= CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}'
              AND state = 'merged'
            ORDER BY merged_at DESC
            LIMIT 10
        """,
        "pagerduty_incidents": """
            SELECT id, title, status, urgency, created_at, escalation_level
            FROM pagerduty.incidents
            WHERE status = 'triggered'
            ORDER BY urgency DESC
        """,
        "slack_messages": """
            SELECT user_id, text, ts
            FROM slack.messages(channel => '{{INCIDENTS_CHANNEL}}')
            WHERE ts >= (CURRENT_TIMESTAMP - INTERVAL '{{SINCE}}')::TEXT
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

    async def investigate(self, question: str) -> dict[str, Any]:
        phase1_data = await self._run_phase1()
        report = self._build_report(question, phase1_data)
        await self._persist_report(report)
        return report

    async def investigate_with_reasoning(
        self, question: str, max_loops: int = 2,
        on_progress: Optional[callable] = None,
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
        return base

    @staticmethod
    def _sanitize_service(service: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "", service)

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
        service_filter = (
            f"AND project = '{safe_service}'" if safe_service else ""
        )
        for source_name, template in self.PHASE1_QUERY_TEMPLATES.items():
            since_val = parsed_since or self.PHASE1_SINCE_DEFAULTS.get(source_name, "")
            query = (
                template
                .replace("{{INCIDENTS_CHANNEL}}", self._incidents_channel)
                .replace("{{SINCE}}", since_val)
                .replace("{{SERVICE_FILTER}}", service_filter if source_name == "sentry_issues" else "")
            )
            try:
                result = await self._coral.query(query)
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
                logger.warning("Phase 1 [%s] failed: %s", source_name, e)
                err_msg = str(e)[:500] if not _is_internal_error(str(e)) else "Internal Coral error"
                data[source_name] = {
                    "rows": [],
                    "row_count": 0,
                    "columns": [],
                    "error": err_msg,
                    "error_code": e.code.value if hasattr(e.code, 'value') else str(e.code),
                }
            except Exception as e:
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

        return {
            "question": question,
            "incident_id": incident_id,
            "summary": " | ".join(summary_parts),
            "evidence_chain": evidence_chain,
            "people_involved": people,
            "suggested_actions": self._suggest_actions(
                sentry_rows, datadog_rows, github_rows, pagerduty_rows
            ),
            "confidence": (
                llm_result.get("confidence", "Medium") if llm_result
                else "Medium (Phase 1 data correlated, no Phase 2 loop yet)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "sentry": {"status": "ok" if sentry_rows else "empty", "count": len(sentry_rows)},
                "datadog": {"status": "ok" if datadog_rows else "empty", "count": len(datadog_rows)},
                "github": {"status": "ok" if github_rows else "empty", "count": len(github_rows)},
                "pagerduty": {"status": "ok" if pagerduty_rows else "empty", "count": len(pagerduty_rows)},
                "slack": {"status": "ok" if slack_rows else "empty", "count": len(slack_rows)},
            },
            "errors": {
                s: d.get("error") for s, d in phase1.items() if "error" in d
            },
        }

    @staticmethod
    def _build_evidence_chain(
        sentry_rows, datadog_rows, github_rows, pagerduty_rows, slack_rows,
        max_per_source: int = 100,
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

        raw_id = report.get("incident_id", "unknown") or "unknown"
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", raw_id)[:128]
        reports_dir = Path(__file__).resolve().parent.parent / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"{safe_id}.json"
        try:
            with open(report_file, "w") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Report saved to %s", report_file)
        except Exception as e:
            logger.warning("Failed to persist report: %s", e)
