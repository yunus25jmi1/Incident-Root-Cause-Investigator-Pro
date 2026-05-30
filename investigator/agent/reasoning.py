import asyncio
import json
import logging
import os
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a root-cause analysis AI for incident investigation. "
    "You receive data from multiple monitoring sources "
    "(Sentry errors, Datadog incidents, GitHub PRs, PagerDuty pages, Slack messages) "
    "and must determine the root cause of the incident.\n\n"
    "Rules:\n"
    "1. Analyze the evidence chronologically.\n"
    "2. Identify correlations between deploys, error spikes, and alerts.\n"
    "3. If you need more data, write raw SQL SELECT queries in follow_up_sql. "
    "Only query tables listed in Available Tables. "
    "You may only run SELECT queries.\n"
    "4. Always output valid JSON. No markdown fences.\n"
    "5. Be concise but thorough.\n"
    "6. NEVER include Slack special mentions like <!channel>, <!everyone>, "
    "or <!here> in your response.\n"
)

def _source(table: str) -> str:
    use_mock = os.environ.get("USE_MOCK_SOURCES", "true").strip().lower() == "true"
    bundled = {"sentry.issues", "github.pulls", "slack.messages"}
    if use_mock and table in bundled:
        return f"mock_{table}"
    return table

def get_catalog_description() -> str:
    return (
        "Available tables:\n"
        f"- {_source('sentry.issues')}: id, title, level, count, user_count, "
        "first_seen, last_seen, project, status\n"
        f"- {_source('datadog.incidents')}: id, title, status, severity, created, "
        "modified, resolved_at, customer_impacted\n"
        f"- {_source('github.pulls')}: number, title, state, merged, user__login, "
        "merged_at, html_url, base__ref, head__label, owner, repo\n"
        f"- {_source('pagerduty.incidents')}: id, title, status, urgency, created_at, "
        "escalation_level, escalation_policy_id\n"
        f"- {_source('pagerduty.oncalls')}: id, escalation_policy_id, "
        "escalation_level, name, email\n"
        f"- {_source('slack.messages')}: user_id, text, ts, channel, permalink\n"
    )


class ReasoningEngine:
    def __init__(
        self,
        model: str = "meta/llama-3.3-70b-instruct",
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ):
        api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY or OPENAI_API_KEY must be set")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def classify_intent(self, question: str) -> str:
        prompt = (
            'Classify this question into one intent word:\n'
            '- "investigate" — asking about an incident, error, outage, root cause\n'
            '- "postmortem" — requesting a post-incident review or retrospective\n'
            '- "help" — asking how to use the bot, what it can do\n'
            '- "chat" — general conversation, greetings, off-topic\n\n'
            f'Question: "{question}"\n\n'
            'Respond with only the intent word.'
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )
            intent = response.choices[0].message.content.strip().lower().rstrip(".")
            if intent in ("investigate", "postmortem", "help", "chat"):
                return intent
            return "investigate"
        except Exception as e:
            logger.warning("Intent classification failed, defaulting to investigate: %s", e)
            return "investigate"

    async def chat_response(self, question: str) -> str:
        prompt = (
            "You are a friendly Slack bot assistant for incident investigation. "
            "Keep responses brief and helpful. "
            f"If the user is greeting you, greet back. "
            f"If they ask something off-topic, politely redirect to incident investigation.\n\n"
            f"User: {question}"
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Chat response failed: %s", e)
            return "Hey! I can help investigate incidents. Try asking about a specific error or outage."

    @staticmethod
    def _phase1_context(phase1_data: dict[str, Any]) -> str:
        parts = []
        for source_name, data in phase1_data.items():
            if "error" in data:
                parts.append(f"[{source_name}] ERROR: {data['error']}")
            elif data.get("rows"):
                rows = data["rows"]
                if len(rows) > 100:
                    parts.append(
                        f"[{source_name}] {data['row_count']} rows "
                        f"(showing top 5 of {len(rows)}):"
                    )
                    parts.append(json.dumps(rows[:5], indent=2))
                else:
                    parts.append(f"[{source_name}] {data['row_count']} rows:")
                    parts.append(json.dumps(rows, indent=2))
            else:
                parts.append(f"[{source_name}] No data")
        return "\n".join(parts)

    async def analyze(
        self,
        question: str,
        phase1_data: dict[str, Any],
        phase2_results: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        ctx = self._phase1_context(phase1_data)

        p2_extra = ""
        if phase2_results:
            p2_extra = "\n\n## Phase 2 Follow-up Data\n" + json.dumps(
                phase2_results, indent=2, default=str
            )

        prompt = (
            f"## Question\n{question}\n\n"
            f"## Phase 1 Data\n{ctx}\n{p2_extra}\n\n"
            f"## Available Tables\n{get_catalog_description()}\n\n"
            "Respond in JSON:\n"
            '{"root_cause": "...", "analysis": "...", '
            '"timeline": [{"time": "...", "event": "..."}], '
            '"confidence": "High|Medium|Low", '
            '"follow_up_sql": ["SELECT ...", "SELECT ..."], '
            '"suggested_actions": [{"priority": "P0", "description": "..."}]}\n\n'
            "If you need more data, write raw SQL SELECT queries in follow_up_sql. "
            "If you have enough, leave follow_up_sql empty."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
            content = response.choices[0].message.content or ""
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("LLM response was not valid JSON: %s", content[:500])
            return self._fallback()
        except Exception as e:
            logger.error("LLM analysis failed: %s", e)
            return self._fallback(str(e))

    async def analyze_with_loop(
        self,
        question: str,
        phase1_data: dict[str, Any],
        coral_query_fn,
        max_loops: int = 2,
        incidents_channel: str = "incidents",
        on_phase2_start: Optional[callable] = None,
        on_query: Optional[callable] = None,
        retry_budget: int = 2,
        max_consecutive_failures: int = 3,
    ) -> dict[str, Any]:
        phase2_results: list[dict[str, Any]] = []
        consecutive_failures = 0
        for iteration in range(max_loops):
            result = await self.analyze(question, phase1_data, phase2_results)
            follow_up_sql = result.get("follow_up_sql", [])

            if not follow_up_sql:
                return result

            if on_phase2_start:
                await on_phase2_start()

            for sql in follow_up_sql:
                filled = sql.replace("{{INCIDENTS_CHANNEL}}", incidents_channel)
                success = False
                for attempt in range(retry_budget + 1):
                    try:
                        qr = await coral_query_fn(filled)
                        phase2_data = {
                            "sql": filled[:200],
                            "rows": qr.rows,
                            "row_count": qr.row_count,
                        }
                        phase2_results.append(phase2_data)
                        logger.info("Phase 2 SQL (%d rows): %s", qr.row_count, filled[:100])
                        success = True
                        if on_query:
                            await on_query(phase2_data)
                        break
                    except Exception as e:
                        logger.warning("Phase 2 SQL failed (attempt %d/%d): %s — %s",
                                       attempt + 1, retry_budget + 1, filled[:100], e)
                        if attempt < retry_budget:
                            await asyncio.sleep(1.0)
                if not success:
                    phase2_results.append({
                        "sql": filled[:200],
                        "error": "Query failed after retries",
                    })
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

                if consecutive_failures >= max_consecutive_failures:
                    logger.warning("Phase 2: %d consecutive failures, exiting loop",
                                   consecutive_failures)
                    break

        return await self.analyze(question, phase1_data, phase2_results)

    @staticmethod
    def _fallback(error: str = "Unknown error") -> dict[str, Any]:
        return {
            "root_cause": "Analysis unavailable",
            "analysis": f"LLM analysis failed: {error}",
            "timeline": [],
            "confidence": "Low",
            "follow_up_sql": [],
            "suggested_actions": [],
        }
