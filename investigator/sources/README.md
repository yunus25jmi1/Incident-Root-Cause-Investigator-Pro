# Sources

This directory defines the data sources available to the agent through Coral.

## Layout

```
sources/
└── mocks/                    # Mock data for demo (JSONL backend)
    ├── datadog.yaml          # Coral source spec — 1 table: incidents
    ├── datadog/
    │   ├── incidents.jsonl   # Currently active scenario (symlinked by activate)
    │   ├── scenario-1.jsonl  # "PR merge broke checkout"
    │   ├── scenario-2.jsonl  # "Database slowdown"
    │   └── scenario-3.jsonl  # "Deployment config drift"
    ├── pagerduty.yaml        # Coral source spec — 2 tables: incidents, oncalls
    └── pagerduty/
        ├── incidents.jsonl   # Currently active scenario
        ├── oncalls.jsonl     # Currently active on-call roster
        ├── scenario-1.jsonl
        ├── scenario-2.jsonl
        ├── scenario-3.jsonl
        ├── oncalls-scenario-1.jsonl
        ├── oncalls-scenario-2.jsonl
        └── oncalls-scenario-3.jsonl
```

## Real Sources

These are configured in Coral directly (not in this directory):

| Source  | Type    | How Coral connects                     |
|---------|---------|----------------------------------------|
| Sentry  | Real    | Sentry API via Coral's Sentry plugin   |
| GitHub  | Real    | GitHub API via Coral's GitHub plugin   |
| Slack   | Real    | Slack API via Coral's Slack plugin     |

## Mock Sources

Datadog and PagerDuty use Coral's `backend: jsonl` source type. The YAML specs
point at the `mocks/` subdirectory. To switch which data is served:

```bash
# Generate all 3 scenario files (idempotent)
python -m investigator.scripts.generate_mock

# Activate a specific scenario (copies scenario-N.jsonl → incidents.jsonl)
python -m investigator.scripts.generate_mock --activate 2

# Coral picks up the new data on the next query — no restart needed.
```

## Coral Source Specs

- **`datadog.yaml`** — `backend: jsonl`, globs `datadog/incidents.jsonl`, 1 table (incidents)
- **`pagerduty.yaml`** — `backend: jsonl`, globs `pagerduty/incidents.jsonl` and `pagerduty/oncalls.jsonl`, 2 tables (incidents, oncalls)

Both use `dsl_version: 3` for Coral 0.2.1 compatibility. Adding a real Datadog
or PagerDuty source means replacing the `backend: jsonl` with the appropriate
Coral plugin and updating the connection details — no agent code changes needed.
