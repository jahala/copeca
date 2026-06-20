"""Test copeca Scenario model and YAML loader.

These cover the Scenario Pydantic model validation and YAML roundtripping.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from copeca.config.loader import load_scenario
from copeca.config.models import Scenario

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SCENARIO_DIR = Path(__file__).resolve().parent.parent.parent / "scenarios"


class TestScenarioModel:
    """Scenario model validation — pure Pydantic, no filesystem."""

    def test_minimal_scenario_constructs(self):
        scenario = Scenario(
            name="minimal",
            tasks=["t001", "t002"],
        )
        assert scenario.name == "minimal"
        assert scenario.tasks == ["t001", "t002"]
        assert scenario.modes == ["baseline"]
        assert scenario.models == ["claude-sonnet-4-6"]
        assert scenario.repetitions == 1
        assert scenario.budget_usd == 1.0
        assert scenario.timeout_seconds == 300
        assert scenario.max_workers == 1
        assert scenario.output_dir == "results"

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError, match="name"):
            Scenario(name="", tasks=["t001"])

    def test_empty_tasks_raises(self):
        with pytest.raises(ValidationError, match="tasks"):
            Scenario(name="test", tasks=[])

    def test_zero_repetitions_raises(self):
        with pytest.raises(ValidationError, match="repetitions"):
            Scenario(name="test", tasks=["t001"], repetitions=0)

    def test_negative_budget_raises(self):
        with pytest.raises(ValidationError, match="budget_usd"):
            Scenario(name="test", tasks=["t001"], budget_usd=-1.0)

    def test_negative_max_workers_raises(self):
        with pytest.raises(ValidationError, match="max_workers"):
            Scenario(name="test", tasks=["t001"], max_workers=0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValidationError, match="timeout_seconds"):
            Scenario(name="test", tasks=["t001"], timeout_seconds=-1)

    def test_scenario_yaml_roundtrips(self):
        scenario = Scenario(
            name="roundtrip-test",
            description="A scenario for roundtrip testing.",
            tasks=["t001_find_matcher_trait", "t002_fastapi_routing"],
            modes=["baseline", "experimental"],
            models=["claude-sonnet-4-6", "deepseek-v4-pro"],
            repetitions=3,
            budget_usd=5.0,
            timeout_seconds=600,
            max_workers=4,
            output_dir="results/my_run",
        )
        dumped = yaml.dump(scenario.model_dump())
        reloaded = yaml.safe_load(dumped)
        validated = Scenario.model_validate(reloaded)
        assert validated == scenario


class TestLoadScenario:
    """load_scenario reads YAML, constructs Scenario."""

    def test_valid_scenario_loads(self):
        scenario = load_scenario(SCENARIO_DIR / "example.yaml")
        assert isinstance(scenario, Scenario)
        assert scenario.name == "example-benchmark"
        assert "t001_find_matcher_trait" in scenario.tasks
        assert "t002_fastapi_routing" in scenario.tasks
        assert scenario.modes == ["baseline"]
        assert scenario.repetitions == 1

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_scenario(SCENARIO_DIR / "nonexistent.yaml")

    def test_malformed_yaml_raises(self):
        tmp = FIXTURES / "scenarios" / "malformed.yaml"
        with pytest.raises(Exception):
            load_scenario(tmp)


class TestShippedScenario:
    """Verify the shipped scenarios/example.yaml is valid and references real tasks."""

    def test_example_scenario_loads(self) -> None:
        """The shipped scenarios/example.yaml must be valid and loadable."""
        scenario = load_scenario(SCENARIO_DIR / "example.yaml")
        assert scenario.name is not None
        assert len(scenario.tasks) > 0
        assert len(scenario.models) > 0

    def test_example_scenario_tasks_exist_in_corpus(self) -> None:
        """Tasks referenced in example.yaml should exist in tasks/."""
        scenario = load_scenario(SCENARIO_DIR / "example.yaml")
        tasks_dir = (
            Path(__file__).resolve().parent.parent.parent / "tasks"
        )
        available: set[str] = set()
        for yf in tasks_dir.rglob("*.yaml"):
            doc = yaml.safe_load(yf.read_text())
            if isinstance(doc, dict) and "name" in doc:
                available.add(doc["name"])
        for task_name in scenario.tasks:
            assert (
                task_name in available
            ), f"Scenario references '{task_name}' which is not in tasks/"
