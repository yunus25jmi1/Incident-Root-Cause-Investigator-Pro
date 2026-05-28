# 3-Minute Demo Script

**Setup:** Terminal 1 = `coral mcp-stdio` running. Terminal 2 = `python -m investigator.bot.handler`. Slack workspace open.

---

### 0:00 — Opening

> "Every engineer knows this pain. Incident happens, you spend 15 minutes clicking through 5 tools to figure out what broke.
>
> I built an agent that does it in 2 seconds — and it posts the answer to Slack. Let me show you."

---

### 0:15 — The Ask

Type in Slack:

```
@investigator what caused the 5xx spike?
```

Bot responds with:
1. `🔍 Investigating...`
2. `📡 Phase 1: Gathering data from 5 sources...`
3. `🧠 Analyzing initial signals...`
4. `🔬 Phase 2: Running follow-up queries...` (if needed)
5. `✅ Investigation complete. Generating report...`
6. Full Block‑Kit report with summary, evidence chain, people, actions

---

### 1:00 — Walk Through the Report

Point to each section:

1. **Summary** — "Root cause: PR #4321 by Alice → NullReferenceException spike"
2. **Evidence Chain** — 5+ events in chronological order across all 5 tools
3. **Who's Involved** — Alice (PR author), Bob (on-call SRE), Slack participants
4. **Suggested Actions** — Revert PR, add null check, acknowledge PagerDuty, schedule postmortem

> "Every link in this report is clickable — the PR, the Sentry issue. One click and you're in context."

---

### 1:30 — The Agent Loop Reveal

> "This isn't a fixed SQL script. Watch — I'll ask a different question."

Switch to Scenario 2:

```bash
python -m investigator.scripts.generate_mock --activate 2
```

Ask:

```
@investigator why is checkout slow?
```

Bot runs investigation against Scenario 2 (database slowdown). Different data, different question, different answer.

> "I swapped the mock data between runs. The agent didn't know. It queried, discovered database pool exhaustion, and produced a completely different root cause. That's genuine agentic behavior — not a script."

---

### 2:00 — The SQL

> "Here's what powers the Phase 1 discovery."

```sql
SELECT g.title, g.merged_at, g.user__login,
       s.title, s.level, s.count
FROM github.pull_requests g
JOIN sentry.issues s ON s.first_seen >= g.merged_at
WHERE g.merged_at >= CURRENT_TIMESTAMP - INTERVAL '4 hours'
  AND s.level IN ('error', 'fatal')
ORDER BY s.count DESC;
```

> "Coral translates this SQL into actual API calls. GitHub API for PRs, Sentry API for errors. It handles auth, pagination, rate limits — all below deck."

---

### 2:30 — The /postmortem Differentiator

```
/postmortem --incident INC789
```

> "Investigation is step one. The second step is documenting what happened. One more command generates a complete postmortem draft."

---

### 2:45 — The Switch

Open `investigator/sources/mocks/datadog.yaml`:

> "This project uses real Sentry, real GitHub, real Slack — and 2 mock sources for Datadog and PagerDuty because free tiers are limited. But switching to real sources is one command:"

```bash
coral source remove datadog
coral source add <datadog-plugin-config>
```

> "Same code, same queries, now hitting the real Datadog API. Zero changes to the agent."

---

### 2:55 — Close

> "Coral turns 5 separate tools into 1 queryable database. The agent just writes SQL. Everything else — auth, pagination, rate limits — handled below deck."
