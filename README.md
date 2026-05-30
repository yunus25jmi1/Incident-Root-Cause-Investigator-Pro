# Incident Root-Cause Investigator Pro

A Slack-native AI agent that automates incident root‑cause investigation by joining data across **5 sources** through [Coral](https://withcoral.com) SQL.

> **Hackathon:** Pirates of the Coral‑bean — Track 1 (Build an Enterprise Agent)

---

## Features

- **`@investigator what caused the 5xx spike?`** — get a root-cause hypothesis with evidence from GitHub, Sentry, Datadog, PagerDuty, and Slack
- **`/postmortem --incident INC789`** — generate a post-incident review from a saved investigation
- **`--since 3h` / `--service checkout`** — narrow time windows and services
- **Agent loop** — the LLM can request follow-up SQL queries when it needs more data
- **Predictive risk projection** — anticipates service degradation, cascade failures, and connection pool exhaustion
- **Parallel universe simulator** — models "what if" rollback scenarios with recovery timelines
- **Temporal replay scrubber** — step through the incident timeline in the web UI
- **Cascading failure graph** — visual dependency chain of error propagation across sources
- **Comprehensive mock data** — 30-44 realistic records per source covering 3+ incident storylines

## Architecture

```
                    ┌─────────────┐
  Slack ───────────▶│  Bolt Bot    │──▶ InvestigationQueue (serial)
                    │ (Socket Mode)│
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  AgentCore   │─── Phase 1: 5 parallel SQL queries
                    │ + Reasoning  │─── Phase 2: LLM-driven follow-up SQL
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Coral MCP   │─── 5 SQL sources
                    │  (stdio)     │
                    └─────────────┘
```

All data access goes through **Coral MCP stdio** — zero direct API calls to the underlying sources.

## Getting Started

### Prerequisites

- Python 3.11+
- [Coral v0.2.1](https://withcoral.com) installed and on your PATH
- A Slack workspace with Socket Mode enabled
- An NVIDIA NIM API key (free tier) or OpenAI API key

### Setup

```bash
git clone <repo>
cd incident-root-cause-investigator-pro

# Create venv, install deps
make setup

# Edit .env with your API keys
# At minimum: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, NVIDIA_API_KEY
nano .env

# Generate comprehensive mock data for all 5 sources
python -m investigator.scripts.seed_all --activate

# Start the bot
make run
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Slack bot token (starts with `xoxb-`) |
| `SLACK_APP_TOKEN` | Yes | Slack app-level token (starts with `xapp-`) |
| `NVIDIA_API_KEY` | One of | NVIDIA NIM API key |
| `OPENAI_API_KEY` | One of | OpenAI API key (fallback) |
| `OPENAI_BASE_URL` | No | Custom LLM endpoint |
| `INCIDENTS_CHANNEL` | No | Slack channel ID for message queries (default: `incidents`) |
| `ALLOWED_CHANNELS` | No | Comma-separated list of allowed channel IDs |
| `GITHUB_OWNER` | No | GitHub owner/org for live PR queries |
| `GITHUB_REPO` | No | GitHub repo name for live PR queries |
| `USE_MOCK_SOURCES` | No | Set to `true` to query mock sources instead of live APIs (default: `true`) |
| `SENTRY_DSN` | Optional | Sentry DSN for seed-sentry |
| `CORAL_COMMAND` | No | Coral binary path (default: `coral`) |
| `API_KEY` | No | API key for web endpoint auth (Bearer token) |
| `QUEUE_ENCRYPTION_KEY` | No | Fernet key for queue state encryption at rest |

### Mock Data

Mock imported sources (`mock_sentry`, `mock_github`, `mock_slack`) provide 30-44 realistic records each, covering 3 incident storylines:

| Incident | PR | Sentry Error | Datadog | PagerDuty |
|---|---|---|---|---|
| PR merge broke checkout | #4321 Alice | ZeroDivisionError (847) | SEV-2 | INC789 |
| Database pool exhaustion | #4323 Charlie → reverted | ConnectionTimeoutError (1560) | SEV-3 | INC790 |
| Config drift — HTTP 502 | #4325 Alice | Http502Error (2100) | SEV-2 | INC791 |

Regenerate anytime:

```bash
python -m investigator.scripts.seed_all --activate
```

## Testing

```bash
# All tests
make test
# or
python -m pytest investigator/tests/ -v

# With coverage
make test-coverage
```

**281 tests** (3 skipped — require real Coral running).

## Project Structure

```
investigator/
├── agent/
│   ├── coral_client.py     # MCP stdio client wrapper (connect/query/catalog)
│   ├── core.py             # AgentCore — Phase 1 queries, evidence chain, report
│   └── reasoning.py        # ReasoningEngine — intent classification, Phase 2 loop
├── bot/
│   ├── handler.py          # Slack Bolt handler (app_mention, /postmortem)
│   ├── queue.py            # InvestigationQueue — serial async worker + encryption
│   └── formatter.py        # Block‑Kit builders for Slack messages
├── lib/
│   ├── rate_limiter.py     # Per-user sliding window rate limiter
│   └── sanitizer.py        # ErrorSanitizer — path/token/env-var redaction
├── web/
│   ├── app.py              # FastAPI server with SSE streaming + API key auth
│   ├── templates/index.html # Dark-theme UI with replay + simulation views
│   └── static/style.css
├── scripts/
│   ├── generate_mock.py    # Legacy JSONL mock generator (3 scenarios)
│   ├── seed_all.py         # Comprehensive mock data for all 5 sources
│   └── seed_sentry.py      # Push test errors to Sentry
├── sources/mocks/
│   ├── {datadog,pagerduty,sentry,github,slack}.yaml  # Coral source specs
│   └── {datadog,pagerduty,sentry,github,slack}/       # Generated JSONL data
└── tests/
    ├── test_coral_client.py   # 89 tests — MCP client, ReadOnlyValidator, edge cases
    ├── test_reasoning.py      # 30+ tests — intent, Phase 2 loop, error paths
    ├── test_formatter.py      # 31 tests — Block‑Kit builders, mrkdwn sanitization
    ├── test_integration.py    # 40+ tests — AgentCore, evidence chain, multi-scenario
    ├── test_queue.py          # 11 tests — concurrency, cancellation, error resilience
    ├── test_e2e.py            # 14 tests — mock-based end-to-end flows
    ├── test_setup.py          # 20 tests — setup integrity, imports, mock generation
    ├── test_rate_limiter.py   # Rate limiter concurrency tests
    └── test_sanitizer.py      # ErrorSanitizer redaction + truncation tests
```

## Security

| Layer | Mechanism |
|---|---|
| SQL injection | Parameterized queries (`$service` placeholder); `ReadOnlyValidator` rejects non-SELECT/WITH; `_sanitize_service()` strips to `[a-zA-Z0-9_.-]` |
| API authentication | Optional `Bearer` token via `API_KEY` env var on all `/api/*` endpoints |
| Rate limiting | Per-user sliding window (Slack) + per-IP (web), configurable limits |
| Error sanitization | Regex redaction of paths, tokens, env vars before Slack output |
| LLM output | HTML/script tags stripped before persisting reports to disk |
| Queue state | Optional Fernet encryption at rest via `QUEUE_ENCRYPTION_KEY` |
| Command injection | `CORAL_COMMAND` resolved to absolute path; `shutil.which()` validates existence |
| XSS prevention | `textContent`-based HTML escaping in web UI; allowlist validation for types/priorities |
| Docker | Runs as `appuser` (non-root); seed scripts execute under restricted user |
| Request size | 10 KB body cap via middleware on all web endpoints |
| Dependencies | Pinned exact versions in `requirements.txt`; no `>=` ranges |

**Security audit** — all 9 findings from the initial review are resolved. See commit `8aaa45e`.

## Key Design Decisions

- **No direct API calls** — everything through Coral MCP. Mock sources use `backend: jsonl`.
- **Serial queue** — `InvestigationQueue` processes one investigation at a time, with backpressure at queue size 10.
- **Phase 1 + Phase 2** — Phase 1 runs 5 parallel SQL queries (one per source). Phase 2 lets the LLM request additional SQL based on findings.
- **SQL is read-only** — validated by `ReadOnlyValidator` before every query.
- **Reports are local JSON** — stored in `investigator/data/reports/` for the `/postmortem` command.
- **Sentry** — error reporting via `sentry_sdk.init()` in both web app and bot lifespans, gated on `SENTRY_DSN`.

## Demo

1. Start Coral: `coral mcp-stdio`
2. Start the bot: `make run`
3. In Slack: `@investigator what caused the 5xx spike?`
4. The bot responds with progress updates and delivers a Block‑Kit report
5. Check for saved report: `/postmortem --incident INC789`

---

*Built for Pirates of the Coral‑bean 2026*
