# Building a Slack-Native AI Incident Investigator with Coral SQL

*May 26, 2026*

When production breaks, the clock starts. Every minute of manual context-gathering — checking Datadog, jumping into Sentry, scrolling Slack, finding who's on call — is a minute your users are hitting errors.

For Pirates of the Coral‑bean 2026 (Track 1: Build an Enterprise Agent), I built a Slack-native AI agent that automates those first 15 minutes. You `@investigator what caused the 5xx spike?` and it returns a root‑cause hypothesis with evidence from 5 sources, all correlated through Coral SQL.

## Why Slack-Native?

Most incident investigation tools add yet another dashboard. But during an incident, engineers are already in Slack. The agent should come to them, not the other way around.

The agent uses Slack Socket Mode (no public URL needed) and responds in the thread where it was mentioned. Progress updates appear as the investigation unfolds: "📡 Querying Sentry...", "🔄 Phase 2: running follow-up SQL...", "✅ Complete".

## Architecture in 3 Layers

```
Slack Bot (Bolt for Python)
    └── InvestigationQueue (serial worker)
        └── AgentCore + ReasoningEngine
            └── Coral MCP stdio
                ├── Sentry (real)
                ├── GitHub (real)
                ├── Datadog (jsonl mock)
                ├── PagerDuty (jsonl mock)
                └── Slack (real, via Coral plugin)
```

Every data access goes through a single Coral MCP stdio connection — zero direct API calls. This is the key simplification: instead of maintaining 5 SDK integrations with rate limits and auth, there's one uniform SQL interface.

### Phase 1: Parallel Source Queries

When a question comes in, the agent runs 5 SQL queries in parallel:

```sql
SELECT id, title, level, count FROM sentry.issues
WHERE last_seen >= CURRENT_TIMESTAMP - INTERVAL '4 hours';

SELECT id, title, severity FROM datadog.incidents
WHERE status = 'active';
```

### Phase 2: LLM-Driven Follow-Up

After Phase 1, the LLM (NVIDIA NIM Llama 3.1 Nemotron 70B) analyzes the results and can request follow-up SQL. This is the agent loop — the model decides it needs more data and the agent fetches it:

```
LLM: "I see an error spike in checkout-service. Query the specific error details."
Agent: SELECT * FROM sentry.issues WHERE project = 'checkout-service'
LLM: "Found it — NullReferenceException from PR #4321. Here's the full analysis."
```

This loop runs up to 2 iterations max, with progress callbacks updating Slack at each step.

## The Mock Data Strategy

For 2 of the 5 sources (Datadog, PagerDuty), I used Coral's JSONL backend to create mock data files. Three scenarios are pre-built:

1. **PR merge broke checkout** — A merged PR introduces a null pointer, error spike, and SEV-2 page
2. **Database slowdown** — A schema migration causes connection pool exhaustion
3. **Deployment config drift** — Config changes break authentication

Each scenario is a self-contained JSONL file with correlated IDs across Datadog and PagerDuty. Switching scenarios is a single command:

```bash
python -m investigator.scripts.generate_mock --activate 2
```

## Security Details

- **Read-only SQL** — A `ReadOnlyValidator` strips any DDL/DML before it reaches Coral
- **Slack mention sanitization** — `<!channel>`, `<!everyone>`, `<!here>` are replaced before any bot output
- **Path traversal protection** — Incident IDs for `/postmortem` are sanitized with regex
- **Error messages are scrubbed** — Internal stack traces never reach Slack

## Current Stats

- **234 passing tests** (3 skipped — require real Coral)
- **5 data sources** (3 real, 2 mock)
- **~1200 lines of agent/bot code**
- **~1800 lines of tests**

## What I'd Do Next

- **Per‑user rate limiting** — the queue is serial per bot instance, but one user could DOS another
- **Persistent investigation history** — Slack messages expire; a lightweight DB would preserve context
- **LLM provider fallback** — currently picks one at init; automatic fallback would improve reliability
- **Multi‑workspace support** — the socket mode handler is single-workspace by design

## Try It

Everything is in the repo. Setup takes about 5 minutes:

1. Install Coral v0.2.1
2. Clone the repo, `make setup`, fill in `.env`
3. `make seed-mock && make run`
4. `@investigator what caused the 5xx spike?`

---

*Built for Pirates of the Coral‑bean 2026 — a solo hackathon project in 7 days.*
