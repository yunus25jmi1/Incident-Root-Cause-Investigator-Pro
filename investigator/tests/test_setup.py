"""
Setup-script integrity test: validates the fresh-clone → working-bot workflow.

Tests are intentionally filesystem-heavy and skip if prerequisites are missing
(pip, Python, etc.) so they can run in CI or on a fresh clone.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
MOCKS_DIR = PROJECT_ROOT / "investigator" / "sources" / "mocks"


class TestRequirements:
    def test_requirements_file_exists(self):
        assert REQUIREMENTS.exists(), "requirements.txt not found"

    def test_requirements_are_readable(self):
        content = REQUIREMENTS.read_text()
        assert content.strip(), "requirements.txt is empty"
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                assert "=" in line or ">=" in line, f"Invalid requirement: {line}"

    def test_core_dependencies(self):
        for pkg in ("mcp", "slack_bolt", "openai", "dotenv", "pytest", "httpx"):
            try:
                __import__(pkg)
            except ImportError:
                pytest.skip(f"{pkg} not installed — cannot verify")

    def test_all_app_modules_importable(self):
        modules = [
            "investigator.agent.coral_client",
            "investigator.agent.core",
            "investigator.agent.reasoning",
            "investigator.bot.queue",
            "investigator.bot.formatter",
            "investigator.scripts.generate_mock",
            "investigator.scripts.seed_sentry",
        ]
        for mod in modules:
            try:
                __import__(mod)
            except ImportError as e:
                pytest.fail(f"Module {mod} failed to import: {e}", pytrace=False)


class TestMakeSetup:
    def test_makefile_exists(self):
        makefile = PROJECT_ROOT / "Makefile"
        assert makefile.exists()

    def test_make_targets_listed(self):
        makefile = PROJECT_ROOT / "Makefile"
        content = makefile.read_text()
        for target in ("install", "test", "setup", "seed-mock", "run", "verify"):
            assert f"{target}:" in content, f"Missing make target: {target}"

    def test_data_reports_dir_creatable(self, tmp_path):
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        assert reports.exists()
        assert reports.is_dir()

    def test_env_example_copied(self, tmp_path):
        dest = tmp_path / ".env"
        example = PROJECT_ROOT / ".env.example"
        if not example.exists():
            pytest.skip(".env.example not found")
        dest.write_text(example.read_text())
        assert dest.exists()
        content = dest.read_text()
        assert "SLACK_BOT_TOKEN" in content
        assert "NVIDIA_API_KEY" in content


class TestMockDataGeneration:
    def test_mock_base_dir_exists(self):
        assert MOCKS_DIR.exists(), f"Mock directory not found: {MOCKS_DIR}"
        assert MOCKS_DIR.is_dir()

    def test_datadog_yaml_exists(self):
        yaml_file = MOCKS_DIR / "datadog.yaml"
        assert yaml_file.exists(), f"Missing: {yaml_file}"

    def test_pagerduty_yaml_exists(self):
        yaml_file = MOCKS_DIR / "pagerduty.yaml"
        assert yaml_file.exists(), f"Missing: {yaml_file}"

    def test_mock_data_dirs_exist(self):
        for sub in ("datadog", "pagerduty"):
            d = MOCKS_DIR / sub
            assert d.exists() and d.is_dir(), f"Missing mock dir: {d}"

    def test_generate_all_scenarios(self, tmp_path):
        from investigator.scripts.generate_mock import generate_scenario
        for i in (1, 2, 3):
            generate_scenario(i, output_dir=str(tmp_path))
            assert (tmp_path / "datadog" / f"scenario-{i}.jsonl").exists()
            assert (tmp_path / "pagerduty" / f"scenario-{i}.jsonl").exists()

    def test_activate_scenario(self, tmp_path):
        from investigator.scripts.generate_mock import generate_scenario, activate_scenario
        generate_scenario(1, output_dir=str(tmp_path))
        activate_scenario(1, output_dir=str(tmp_path))
        assert (tmp_path / "datadog" / "incidents.jsonl").exists()
        content = (tmp_path / "datadog" / "incidents.jsonl").read_text()
        assert "dd-inc-001" in content
        assert (tmp_path / "pagerduty" / "incidents.jsonl").exists()
        assert (tmp_path / "pagerduty" / "oncalls.jsonl").exists()

    def test_list_scenarios(self, capsys):
        from investigator.scripts.generate_mock import list_scenarios
        list_scenarios()
        captured = capsys.readouterr()
        assert "PR merge broke checkout" in captured.out
        assert "Database slowdown" in captured.out

    def test_seed_sentry_argument_parsing(self):
        from investigator.scripts.seed_sentry import validate_env

        with pytest.raises(SystemExit):
            import os
            old = os.environ.pop("SENTRY_DSN", None)
            try:
                validate_env()
            finally:
                if old:
                    os.environ["SENTRY_DSN"] = old


class TestImportsAtRuntime:
    def test_coral_client_imports(self):
        from investigator.agent.coral_client import CoralClient, CoralError, QueryResult
        assert CoralClient is not None

    def test_queue_imports(self):
        from investigator.bot.queue import InvestigationQueue
        assert InvestigationQueue is not None

    def test_reasoning_imports(self):
        from investigator.agent.reasoning import ReasoningEngine
        assert ReasoningEngine is not None

    def test_formatter_imports(self):
        from investigator.bot.formatter import investigation_report, postmortem_report
        assert investigation_report is not None

    def test_core_imports(self):
        from investigator.agent.core import AgentCore
        assert AgentCore is not None
