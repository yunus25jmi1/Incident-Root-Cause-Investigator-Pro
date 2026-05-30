import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_SECTION_TEXT = 3000


def _truncate(text: str, max_len: int = MAX_SECTION_TEXT) -> str:
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _sanitize_mrkdwn(text: str) -> str:
    text = text.replace("<!channel>", "[channel]")
    text = text.replace("<!everyone>", "[everyone]")
    text = text.replace("<!here>", "[here]")
    text = re.sub(r"<!channel\|[^>]*>", "[channel]", text)
    text = re.sub(r"<!everyone\|[^>]*>", "[everyone]", text)
    text = re.sub(r"<!here\|[^>]*>", "[here]", text)
    return text


def progress_block(emoji: str, text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} {_truncate(text)}",
            },
        }
    ]


def progress_update(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def investigation_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": "🚨 Incident Analysis Report"},
    })
    blocks.append({"type": "divider"})

    root_cause = report.get("root_cause")
    if root_cause:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔍 Root Cause*\n{_truncate(_sanitize_mrkdwn(root_cause))}"},
        })

    analysis = report.get("analysis")
    if analysis:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🧠 Analysis*\n{_truncate(_sanitize_mrkdwn(analysis))}"},
        })

    summary = report.get("summary", "No summary available.")
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*📋 Summary*\n{_truncate(_sanitize_mrkdwn(summary))}"},
    })

    evidence = report.get("timeline") or report.get("evidence_chain", [])
    if evidence:
        evidence_text = "*📊 Evidence Chain*\n"
        for i, item in enumerate(evidence[:10], 1):
            if isinstance(item, dict):
                title = _sanitize_mrkdwn(item.get("title", ""))
                detail = _sanitize_mrkdwn(item.get("detail", ""))
                url = item.get("url", "")
                time = item.get("time", "")
                if url:
                    evidence_text += f"{i}. <{url}|{title}> — {detail} ({time})\n"
                else:
                    evidence_text += f"{i}. {title} — {detail} ({time})\n"
            else:
                evidence_text += f"{i}. {_sanitize_mrkdwn(str(item))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(evidence_text))},
        })

    error_count = report.get("errors", {})
    if error_count:
        errors_text = "*⚠️ Source Errors*\n"
        for src, err in list(error_count.items())[:5]:
            if err:
                errors_text += f"• {src}: {_sanitize_mrkdwn(str(err)[:500])}\n"
        if errors_text.strip() != "*⚠️ Source Errors*":
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(errors_text))},
            })

    people = report.get("people_involved", [])
    if people:
        people_text = "*👤 Who's Involved*\n"
        for p in people[:10]:
            if isinstance(p, dict):
                name = _sanitize_mrkdwn(p.get("name", "Unknown"))
                role = _sanitize_mrkdwn(p.get("role", ""))
                people_text += f"• {name} ({role})\n"
            else:
                people_text += f"• {_sanitize_mrkdwn(str(p))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(people_text))},
        })

    actions = report.get("suggested_actions", [])
    if actions:
        actions_text = "*🎯 Suggested Actions*\n"
        for a in actions[:5]:
            if isinstance(a, dict):
                priority = a.get("priority", "")
                prefix = "• " + (f"[{priority}] " if priority else "")
                actions_text += f"{prefix}{_sanitize_mrkdwn(a.get('description', ''))}\n"
            else:
                actions_text += f"• {_sanitize_mrkdwn(str(a))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(actions_text))},
        })

    predictions = report.get("predictions", [])
    if predictions:
        pred_text = "*🔮 Predictions*\n"
        for p in predictions[:4]:
            if isinstance(p, dict):
                sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
                icon = sev_icon.get(p.get("severity", ""), "⚪")
                conf = int((p.get("confidence", 0) or 0) * 100)
                pred_text += f"{icon} *{_sanitize_mrkdwn(p.get('title', ''))}* — {conf}% confidence, {p.get('timeframe', '')}\n{_sanitize_mrkdwn(p.get('description', ''))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(pred_text)},
        })

    simulation = report.get("simulation")
    if simulation:
        sim_text = (
            f"*🎮 Parallel Universe Simulation*\n"
            f"• *Scenario:* {_sanitize_mrkdwn(simulation.get('scenario', ''))}\n"
            f"• *Confidence:* {int((simulation.get('confidence', 0) or 0) * 100)}%\n"
            f"• *Outcome:* ✅ {simulation.get('outcome', '')}\n"
        )
        timeline = simulation.get("timeline", [])
        if timeline:
            sim_text += "*Recovery Timeline:*\n"
            for s in timeline[:4]:
                sim_text += f"  `{s.get('time', '')}` {_sanitize_mrkdwn(s.get('event', ''))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(sim_text)},
        })

    source_counts = report.get("sources", {})
    if source_counts:
        sources_text = "*🔌 Sources*\n"
        for sname, sinfo in source_counts.items():
            if isinstance(sinfo, dict):
                status = sinfo.get("status", "?")
                count = sinfo.get("count", 0)
                icon = "✅" if status == "ok" else "⬜"
                sources_text += f"{icon} {sname}: {count} results\n"
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": _truncate(sources_text)},
            ],
        })

    blocks.append({"type": "divider"})
    confidence = report.get("confidence", "N/A")
    timestamp = report.get("timestamp", "")
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"🤖 *Investigator Pro* | Confidence: {confidence} | {timestamp}",
            },
        ],
    })

    return blocks


def postmortem_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": "📝 Post-Incident Review"},
    })
    blocks.append({"type": "divider"})

    incident_id = report.get("incident_id", "N/A")
    summary = report.get("summary", "No data available.")
    ts = report.get("timestamp", "")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*Incident:* {incident_id}\n"
                f"*Date:* {ts[:10] if ts else 'N/A'}\n"
                f"*Question:* {report.get('question', 'N/A')}"
            ),
        },
    })
    blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*🔍 Root Cause*\n{_truncate(_sanitize_mrkdwn(summary))}"},
    })

    evidence = report.get("evidence_chain", [])
    if evidence:
        timeline_text = "*⏱ Timeline*\n"
        for item in evidence[:10]:
            if isinstance(item, dict):
                timeline_text += (
                    f"• `{item.get('time', '?')}` — "
                    f"{_sanitize_mrkdwn(item.get('title', ''))} "
                    f"({_sanitize_mrkdwn(item.get('detail', ''))})\n"
                )
            else:
                timeline_text += f"• {_sanitize_mrkdwn(str(item))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(timeline_text))},
        })

    people = report.get("people_involved", [])
    if people:
        people_text = "*👥 Participants*\n"
        for p in people[:10]:
            if isinstance(p, dict):
                people_text += f"• {_sanitize_mrkdwn(p.get('name', 'Unknown'))} — {_sanitize_mrkdwn(p.get('role', ''))}\n"
            else:
                people_text += f"• {_sanitize_mrkdwn(str(p))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(people_text))},
        })

    actions = report.get("suggested_actions", [])
    if actions:
        actions_text = "*🛠 Action Items*\n"
        for a in actions[:5]:
            if isinstance(a, dict):
                priority = a.get("priority", "")
                checkbox = "- [ ]"
                label = f"({priority})" if priority else ""
                actions_text += f"{checkbox} {label} {_sanitize_mrkdwn(a.get('description', ''))}\n"
            else:
                actions_text += f"- [ ] {_sanitize_mrkdwn(str(a))}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _truncate(_sanitize_mrkdwn(actions_text))},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"📄 Generated by *Investigator Pro* | {ts}",
            },
        ],
    })

    return blocks


def error_message(title: str, details: Optional[str] = None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"❌ *{_truncate(title)}*",
        },
    })
    if details:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{_truncate(details, 2000)}```",
            },
        })
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "Try again or check the logs for more details.",
            },
        ],
    })

    return blocks


def help_message() -> list[dict[str, Any]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🤖 Investigator Pro Help"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Investigate incidents right from Slack.\n\n"
                    "*Commands:*\n"
                    "• `@investigator <question>` — Investigate an incident\n"
                    "• `/postmortem --incident INC123` — Generate post-incident review\n\n"
                    "*Example questions:*\n"
                    "• `@investigator what caused the 5xx spike?`\n"
                    "• `@investigator why is checkout slow?`\n"
                    "• `@investigator what's causing 502s?`\n"
                    "• `@investigator who's on call?`\n\n"
                    "*Supported sources:* GitHub, Sentry, Datadog, PagerDuty, Slack"
                ),
            },
        },
    ]


def not_authorized_message() -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "⚠️ This channel is not authorized for investigations. "
                "Ask your workspace admin to add this channel to `ALLOWED_CHANNELS`.",
            },
        },
    ]
