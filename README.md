# Incident Root-Cause Investigator Pro

A Slack-native AI agent that automates incident root‑cause investigation by joining data across **5 sources** through [Coral](https://withcoral.com) SQL.

> **Hackathon:** Pirates of the Coral‑bean — Track 1 (Build an Enterprise Agent)

---

## Features

- **`@investigator what caused the 5xx spike?`** — get a root-cause hypothesis with evidence from GitHub, Sentry, Datadog, PagerDuty, and Slack
- **`/postmortem --incident INC789`** — generate a post-incident review from a saved investigation
- **`--since 3h` / `--service checkout`** — narrow time windows and services
- **Agent loop** — the LLM can request follow-up SQL queries when it needs more data
- **3 mock scenarios** included for demo and testing

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

# Seed mock data (Datadog + PagerDuty JSONL)
make seed-mock

# (Optional) Push errors to Sentry for real demo
make seed-sentry

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
| `INCEDENTS_CHANNEL` | No | Channel name for {{INCIDENTS_CHANNEL}} substitution |
| `ALLOWED_CHANNELS` | No | Comma-separated list of allowed channel IDs |
| `SENTRY_DSN` | Optional | Sentry DSN for seed-sentry |
| `CORAL_COMMAND` | No | Coral binary path (default: `coral`) |

### Mock Scenarios

Three pre-built incident scenarios are included:

1. **PR merge broke checkout** — PR #4321 merged → NPE spike → SEV-2 → PagerDuty page
2. **Database slowdown** — Migration deploy → PostgreSQL pool exhaustion → SEV-1
3. **Deployment config drift** — Config change → auth errors → 403 spike → SEV-2

Switch between them:

```bash
make activate-scenario SCENARIO=2
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

**234 tests** (3 skipped — require real Coral running).

## Project Structure

```
investigator/
├── agent/
│   ├── coral_client.py     # MCP stdio client wrapper (connect/query/catalog)
│   ├── core.py             # AgentCore — Phase 1 queries, evidence chain, report
│   └── reasoning.py        # ReasoningEngine — intent classification, Phase 2 loop
├── bot/
│   ├── handler.py          # Slack Bolt handler (app_mention, /postmortem)
│   ├── queue.py            # InvestigationQueue — serial async worker
│   └── formatter.py        # Block‑Kit builders for Slack messages
├── scripts/
│   ├── generate_mock.py    # JSONL mock data generator + scenario activator
│   └── seed_sentry.py      # Push test errors to Sentry
├── sources/mocks/
│   ├── datadog.yaml        # Coral source spec (jsonl backend)
│   ├── pagerduty.yaml      # Coral source spec (jsonl backend)
│   ├── datadog/            # Generated JSONL data files
│   └── pagerduty/          # Generated JSONL data files
└── tests/
    ├── test_coral_client.py   # 89 tests — MCP client, ReadOnlyValidator, edge cases
    ├── test_reasoning.py      # 30+ tests — intent, Phase 2 loop, error paths
    ├── test_formatter.py      # 31 tests — Block‑Kit builders, mrkdwn sanitization
    ├── test_integration.py    # 40+ tests — AgentCore, evidence chain, multi-scenario
    ├── test_queue.py          # 11 tests — concurrency, cancellation, error resilience
    ├── test_e2e.py            # 14 tests — mock-based end-to-end flows
    └── test_setup.py          # 20 tests — setup integrity, imports, mock generation
```

## Key Design Decisions

- **No direct API calls** — everything through Coral MCP. Mock sources use `backend: jsonl`.
- **Serial queue** — `InvestigationQueue` processes one investigation at a time, with backpressure at queue size 10.
- **Phase 1 + Phase 2** — Phase 1 runs 5 parallel SQL queries (one per source). Phase 2 lets the LLM request additional SQL based on findings.
- **SQL is read-only** — validated by `ReadOnlyValidator` before every query.
- **Reports are local JSON** — stored in `investigator/data/reports/` for the `/postmortem` command.

## Demo

1. Start Coral: `coral mcp-stdio`
2. Start the bot: `make run`
3. In Slack: `@investigator what caused the 5xx spike?`
4. The bot responds with progress updates and delivers a Block‑Kit report
5. Check for saved report: `/postmortem --incident INC789`

---

*Built for Pirates of the Coral‑bean 2026*
