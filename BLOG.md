# Building a Slack-Native AI Incident Investigator with Coral SQL

*May 29, 2026*

When production breaks, the clock starts. Every minute of manual context-gathering — checking Datadog, jumping into Sentry, scrolling Slack, finding who's on call — is a minute your users are hitting errors.

For Pirates of the Coral‑bean 2026 (Track 1: Build an Enterprise Agent), I built a Slack-native AI agent that automates those first 15 minutes. You `@investigator what caused the 5xx spike?` and it returns a root‑cause hypothesis with evidence from 5 sources, all correlated through Coral SQL.

This post covers both the architecture and the development methodology I used — spec-first, test-driven, delivered in iterative feature phases.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    User Interface                     │
│  ┌─────────────────┐       ┌──────────────────────┐ │
│  │  Slack Bot       │       │  Web Demo (FastAPI)  │ │
│  │  (Bolt/Python)   │       │  SSE streaming       │ │
│  │  Socket Mode     │       │  Dark-theme UI       │ │
│  └────────┬────────┘       └───────────┬──────────┘ │
└───────────┼─────────────────────────────┼───────────┘
            │                             │
            └──────────┬──────────────────┘
                       ▼
           ┌─────────────────────┐
           │   InvestigationQueue │  ← JSONL persistence
           │   (serial worker)    │     for crash recovery
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │  AgentCore          │
           │  + ReasoningEngine  │
           │  (LLM-driven loop)  │
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │  Coral MCP stdio    │  ← unified SQL gateway
           │  ReadOnlyValidator  │     blocks DDL/DML
           │  CatalogCache (60s) │
           └──────────┬──────────┘
                      ▼
     ┌──────┬──────┬──────┬──────┬──────┐
     │Sentry│Datadog│GitHub│PDuty │Slack │
     │ real │ mock  │ real │ mock │ real │
     └──────┴──────┴──────┴──────┴──────┘
```

### The Insight: One SQL Gateway Instead of Five SDKs

Every data access goes through a single Coral MCP stdio connection — zero direct API calls. This is the key simplification: instead of maintaining 5 SDK integrations with rate limits and auth, there's one uniform SQL interface. Coral's MCP protocol lets me add or remove data sources by changing a YAML file, not code.

### Investigation Pipeline: Two-Phase Agent Loop

**Phase 1 — Parallel Source Queries (5 SQL queries concurrently)**

```sql
SELECT id, title, level, count FROM sentry.issues
WHERE last_seen >= CURRENT_TIMESTAMP - INTERVAL '4 hours';

SELECT id, title, severity FROM datadog.incidents
WHERE status = 'active';
```

Each source gets its own SQL query with per-source error isolation — if Sentry is down, the other 4 sources still return data.

**Phase 2 — LLM-Driven Follow-Up**

After Phase 1, the LLM (NVIDIA NIM Llama 3.1 Nemotron 70B) analyzes the results and can request follow-up SQL. This is the agent loop:

```
LLM: "I see a 5xx spike in checkout-service. Let me check the errors."
Agent: SELECT level, count FROM sentry.issues WHERE project = 'checkout-service'
LLM: "Found it — NullReferenceException from PR #4321. Here's the analysis."
```

The loop runs up to 2 iterations with a retry budget of 2 per query, and exits to synthesis after 3 consecutive failures.

---

## The Development Methodology

I structured the project around **Spec Kit** methodology — spec-first, with feature specs driving implementation, testing, and documentation in lockstep.

### Phase 0: Foundation

The initial build created:
- **CoralClient** — MCP stdio wrapper with read-only SQL enforcement
- **AgentCore** — Phase 1 parallel query engine with evidence chain
- **ReasoningEngine** — LLM interaction layer with Phase 2 loop
- **Slack Bot** — Bolt app with serial InvestigationQueue
- **Mock Data Generator** — 3 pre-built incident scenarios as JSONL

This got me to 234 tests and a working `@investigator` bot.

### Phase 1: Error Resilience & Recovery

The first structured feature phase tackled the most common runtime failure: a single source outage killing the entire investigation.

**Spec-driven approach**:
1. Wrote `specs/001-error-resilience/spec.md` — 3 user stories (P1-P3), 100 lines
2. Designed data model: `SourceHealth` dataclass with auto-escalation to FAILED after 3 errors
3. Implemented `retry_with_backoff()` decorator (exponential 1s/2s/4s + jitter)
4. Added `is_transient_error()` — only retries TIMEOUT, CONNECTION_FAILED, MALFORMED_RESPONSE
5. Built `QueuePersistence` as JSONL append-log for crash recovery
6. Bot startup restores pending investigations from disk

**Key metrics**: 3 acceptance scenarios per story, 36 tasks across 6 phases, all passing.

### Phase 2: Performance & Security Hardening

The second phase addressed abuse prevention and query performance.

**Spec-driven approach**:
1. Wrote `specs/002-perf-security/spec.md` — 3 user stories, 100 lines
2. Built `RateLimiter` — per-user sliding window (default 10 req/60s)
3. Built `ErrorSanitizer` — path redaction, env-var redaction, 500-char truncation
4. Added `CatalogCache` — 60s in-memory TTL, protected by `asyncio.Lock`
5. Reduced evidence chain cap from 100 to 20 per source
6. Large result sets (>100 rows) summarized for LLM context

**Key metric**: All engine tests pass in under 3 seconds.

### Phase 3: Web Demo (Hackathon Judging)

The Slack bot required Socket Mode, which needs a persistent connection — not ideal for hackathon judges. I added a FastAPI web app with:

- **SSE streaming** — real-time investigation progress without WebSocket dependency
- **Dark-theme single-page UI** — no build step, no npm, no framework
- **Landing page** — hero section, 3-step explainer, 5-source showcase, architecture diagram
- **Docker support** — `docker compose up` for one-click reproduction

The web app reuses the same AgentCore/ReasoningEngine/CoralClient — zero code duplication. The `on_progress` and `on_phase2_query` callbacks stream events via `asyncio.Queue` to SSE responses.

---

## The Mock Data Strategy

Real API tokens for 5 services is a lot to ask judges to set up. Instead, all sources can operate in mock mode using Coral's JSONL backend.

### The Incident Story

I built one **realistic incident** — CDN Cache Key config drift — inspired by the Cloudflare June 2022 Tiered Cache outage and the Fastly June 2021 global 502 outage:

```
T+0m:   PR #4381 merged — "Optimize cache key for tiered distribution"
T+2m:   CacheKeyMismatchError spikes to 1,462/min
T+3m:   Datadog auto-creates SEV-1 incident
T+4m:   PagerDuty INC-804 triggers high-urgency
T+4.5m: Slack #incidents lights up
T+5m:   Charlie (on-call) acknowledges in Slack
T+6m:   PR #4382 (revert) merged
T+10m:  Cache purge begins
T+47m:  Error rate returns to baseline
T+48m:  INC-804 resolved
T+60m:  Postmortem Slack thread
```

The seed generates **15 Sentry issues, 8 Datadog incidents, 6 GitHub PRs, 10 PagerDuty incidents, 4 oncalls, and 16 Slack messages** — all with correlated IDs and timestamps relative to `datetime.now()`.

---

## Security By Design

The constitution mandates five non-negotiable security properties:

1. **Read-only SQL** — `ReadOnlyValidator` strips any DDL/DML before it reaches Coral
2. **Rate limiting** — per-user sliding window prevents queue flooding
3. **Error sanitization** — paths → `[internal]`, env vars → `[REDACTED]`, truncation at 500 chars
4. **Input validation** — service names sanitized against path traversal, questions capped at 5000 chars
5. **Web layer hardening** — XSS prevention (`escapeHtml()`), CORS with empty origins, non-root Docker user, `shutil.which()` for command validation

---

## Current Stats

| Metric | Value |
|--------|-------|
| Python source files | 28 |
| Total Python lines | ~6,500 |
| Passing tests | 256 |
| Skipped tests | 3 (require real Coral) |
| Spec kit specs | 2 (error-resilience, perf-security) |
| Data sources | 5 (3 real + 2 mock) |
| Test files | 9 |
| Docker image size | ~180MB (slim) |
| Hackathon track | Track 1 — Enterprise Agent |

---

## Lessons Learned

**Coral MCP is the right abstraction**. Zero direct API calls meant I could swap real sources for mock JSONL files without changing a single line of agent code. The same SQL interface works for both.

**Spec-first prevented rework**. Writing the data model and acceptance criteria before coding meant each feature had clear boundaries. When something broke, I knew exactly which spec it violated.

**SSE + asyncio.Queue is surprisingly elegant**. No WebSocket dependency, no polling, no extra infrastructure. FastAPI's `StreamingResponse` with an `asyncio.Queue` feeding it gives real-time progress with minimal code.

**Vanilla JS is fine for a demo**. 387 lines of HTML with embedded JS, 651 lines of CSS, zero build step. For a hackathon where judges are evaluating the *agent*, not the frontend polish, this was the right tradeoff.

---

## Try It

The repo is at `github.com/yunus25jmi1/Incident-Root-Cause-Investigator-Pro`.

```bash
docker compose up --build
# or manually:
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install coral-ai
python -m investigator.scripts.seed_all --activate
uvicorn investigator.web.app:app --host 0.0.0.0 --port 8000
```

Open `http://<vm-ip>:8000`, type a question like "what caused the 5xx spike?", and watch the investigation unfold in real-time.

---

*Built for Pirates of the Coral‑bean 2026 — a solo hackathon project structured around spec-first, test-driven feature delivery.*
