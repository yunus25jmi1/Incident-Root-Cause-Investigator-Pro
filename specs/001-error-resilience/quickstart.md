# Quickstart: Error Resilience Testing

## Test Error Scenarios

```bash
# All tests (existing baseline)
make test

# Focus on error resilience tests
python -m pytest investigator/tests/ -v -k "error or resilient or retry or recover" --tb=short
```

## Manual Testing

### Simulate a source failure

```bash
# Corrupt one mock JSONL file
echo "corrupt" > investigator/sources/mocks/sentry/mock_sentry_issues.jsonl

# Run investigation — should still produce report with sentry marked as "failed"
python -c "
import asyncio
from investigator.agent.coral_client import CoralClient
from investigator.agent.core import AgentCore

async def test():
    async with CoralClient() as coral:
        agent = AgentCore(coral)
        report = await agent.investigate_with_reasoning('what caused the 5xx spike?')
        for src, info in report['sources'].items():
            print(f'{src}: status={info[\"status\"]} count={info[\"count\"]}')
asyncio.run(test())
"

# Restore mock data
python -m investigator.scripts.seed_all --activate
```

### Test queue crash recovery

```bash
# Start bot, enqueue investigations, kill process, restart
# Queue should restore from persisted state
```

## Test Coverage Targets

- `test_coral_client.py`: +8 tests (retry decorator, error classification)
- `test_core.py`: +6 tests (partial failure, source health, report extension)
- `test_reasoning.py`: +5 tests (retry budget, fallback, consecutive failure threshold)
- `test_queue.py`: +6 tests (persistence save/load, crash recovery, corrupt state)
- `test_integration.py`: +3 tests (multi-source failure scenarios)
