"""
Generate mock JSONL data files for Datadog and PagerDuty sources.

This script generates the JSONL files for all 3 incident scenarios.
It can be used to reset or regenerate mock data at any time.

Usage:
    python -m investigator.scripts.generate_mock              # Generate all scenarios
    python -m investigator.scripts.generate_mock --scenario 2 # Generate specific scenario
    python -m investigator.scripts.generate_mock --list       # List available scenarios
"""

import os
import json
import argparse
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sources", "mocks")
)

SCENARIOS = {
    1: {
        "name": "PR merge broke checkout",
        "description": "PR #4321 merged at 14:30 → NPE spike at 14:32 → SEV-2 at 14:33 → INC789 at 14:35",
        "datadog": [
            {
                "id": "dd-inc-001",
                "title": "High error rate on checkout-service",
                "status": "active",
                "severity": "SEV-2",
                "created": "2026-05-24T14:33:00Z",
                "modified": "2026-05-24T14:50:00Z",
                "resolved_at": None,
                "customer_impacted": True,
            }
        ],
        "pagerduty_incidents": [
            {
                "id": "INC789",
                "title": "Checkout service errors spike - SEV-2",
                "status": "triggered",
                "urgency": "high",
                "created_at": "2026-05-24T14:35:00Z",
                "escalation_level": 1,
                "escalation_policy_id": "EP001",
            }
        ],
        "pagerduty_oncall": [
            {
                "id": "oncall-001",
                "escalation_policy_id": "EP001",
                "escalation_level": 1,
                "name": "Bob Smith",
                "email": "bob@company.com",
            }
        ],
    },
    2: {
        "name": "Database slowdown",
        "description": "PR #4330 merged at 15:00 → DB timeout errors at 15:02 → SEV-3 at 15:03 → INC790 at 15:04",
        "datadog": [
            {
                "id": "dd-inc-002",
                "title": "Database connection pool exhaustion",
                "status": "active",
                "severity": "SEV-3",
                "created": "2026-05-24T15:03:00Z",
                "modified": "2026-05-24T15:15:00Z",
                "resolved_at": None,
                "customer_impacted": True,
            }
        ],
        "pagerduty_incidents": [
            {
                "id": "INC790",
                "title": "Database connection pool exhaustion",
                "status": "triggered",
                "urgency": "medium",
                "created_at": "2026-05-24T15:04:00Z",
                "escalation_level": 1,
                "escalation_policy_id": "EP002",
            }
        ],
        "pagerduty_oncall": [
            {
                "id": "oncall-002",
                "escalation_policy_id": "EP002",
                "escalation_level": 1,
                "name": "Diana Chen",
                "email": "diana@company.com",
            }
        ],
    },
    3: {
        "name": "Deployment config drift",
        "description": "PR #4345 merged at 16:00 → HTTP 502 errors at 16:02 → SEV-2 at 16:03 → INC791 at 16:04",
        "datadog": [
            {
                "id": "dd-inc-003",
                "title": "Deployment configuration drift on checkout",
                "status": "active",
                "severity": "SEV-2",
                "created": "2026-05-24T16:03:00Z",
                "modified": "2026-05-24T16:20:00Z",
                "resolved_at": None,
                "customer_impacted": True,
            }
        ],
        "pagerduty_incidents": [
            {
                "id": "INC791",
                "title": "Deployment config drift - HTTP 502 errors",
                "status": "triggered",
                "urgency": "high",
                "created_at": "2026-05-24T16:04:00Z",
                "escalation_level": 1,
                "escalation_policy_id": "EP003",
            }
        ],
        "pagerduty_oncall": [
            {
                "id": "oncall-003",
                "escalation_policy_id": "EP003",
                "escalation_level": 1,
                "name": "Frank Miller",
                "email": "frank@company.com",
            }
        ],
    },
}


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_jsonl(path: str, records: list[dict]) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")
    logger.info("Wrote %d records to %s", len(records), path)


def generate_scenario(scenario_id: int, output_dir: Optional[str] = None) -> None:
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        logger.error("Scenario %d not found. Use --list to see available scenarios.", scenario_id)
        return

    target_dir = output_dir or BASE_DIR
    datadog_dir = os.path.join(target_dir, "datadog")
    pagerduty_dir = os.path.join(target_dir, "pagerduty")
    ensure_dir(datadog_dir)
    ensure_dir(pagerduty_dir)

    write_jsonl(
        os.path.join(datadog_dir, f"scenario-{scenario_id}.jsonl"),
        scenario["datadog"],
    )
    write_jsonl(
        os.path.join(pagerduty_dir, f"scenario-{scenario_id}.jsonl"),
        scenario["pagerduty_incidents"],
    )
    write_jsonl(
        os.path.join(pagerduty_dir, f"oncalls-scenario-{scenario_id}.jsonl"),
        scenario["pagerduty_oncall"],
    )
    logger.info(
        "Generated scenario %d (%s): %s",
        scenario_id,
        scenario["name"],
        scenario["description"],
    )


def activate_scenario(scenario_id: int, output_dir: Optional[str] = None) -> None:
    """Copy scenario files to the default names Coral reads."""
    target_dir = output_dir or BASE_DIR
    datadog_dir = os.path.join(target_dir, "datadog")
    pagerduty_dir = os.path.join(target_dir, "pagerduty")

    src_dd = os.path.join(datadog_dir, f"scenario-{scenario_id}.jsonl")
    dst_dd = os.path.join(datadog_dir, "incidents.jsonl")
    src_pd = os.path.join(pagerduty_dir, f"scenario-{scenario_id}.jsonl")
    dst_pd = os.path.join(pagerduty_dir, "incidents.jsonl")
    src_oc = os.path.join(pagerduty_dir, f"oncalls-scenario-{scenario_id}.jsonl")
    dst_oc = os.path.join(pagerduty_dir, "oncalls.jsonl")

    import shutil
    for src, dst in [(src_dd, dst_dd), (src_pd, dst_pd), (src_oc, dst_oc)]:
        if not os.path.exists(src):
            logger.error("Source file not found: %s. Generate scenarios first.", src)
            return
        shutil.copy2(src, dst)
        logger.info("Activated: %s -> %s", os.path.basename(src), os.path.basename(dst))

    scenario = SCENARIOS.get(scenario_id, {})
    logger.info(
        "Activated scenario %d (%s). Coral picks up new data on next query.",
        scenario_id,
        scenario.get("name", "unknown"),
    )


def list_scenarios() -> None:
    print(f"{'ID':<5} {'Name':<30} {'Description'}")
    print("-" * 80)
    for sid, sdata in sorted(SCENARIOS.items()):
        print(f"{sid:<5} {sdata['name']:<30} {sdata['description']}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate and manage mock incident data"
    )
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2, 3],
        help="Generate a specific scenario (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: sources/mocks/)",
    )
    parser.add_argument(
        "--activate",
        type=int,
        choices=[1, 2, 3],
        help="Activate a scenario (copy to incidents.jsonl)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list:
        list_scenarios()
        return

    if args.activate:
        generate_scenario(args.activate, args.output)
        activate_scenario(args.activate, args.output)
        return

    if args.scenario:
        generate_scenario(args.scenario, args.output)
    else:
        for sid in SCENARIOS:
            generate_scenario(sid, args.output)

    logger.info("All mock data generated. Use --activate <N> to activate a scenario.")


if __name__ == "__main__":
    main()
