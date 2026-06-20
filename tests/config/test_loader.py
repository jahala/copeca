"""Test copeca YAML loader with schema validation.

Tests the two-layer validation: jsonschema (structural) + Pydantic (type safety).
"""

from pathlib import Path

import pytest

from copeca.config.loader import LoadError, SchemaValidationError, load_task, load_tasks_from_dir
from copeca.config.models import ComprehensionGroundTruth, Task, TaskType

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tasks"


class TestLoadTask:
    """load_task reads YAML, validates against schema, constructs Task."""

    def test_valid_task_loads(self):
        task = load_task(FIXTURES / "valid_minimal.yaml")
        assert isinstance(task, Task)
        assert task.name == "rg_trait_implementors"
        assert task.type == TaskType.comprehension
        assert task.source == "SWE-QA (Apache-2.0)"
        assert isinstance(task.ground_truth, ComprehensionGroundTruth)
        assert "Matcher" in task.ground_truth.required_strings

    def test_empty_source_raises(self):
        with pytest.raises(SchemaValidationError, match="source"):
            load_task(FIXTURES / "invalid_missing_source.yaml")

    def test_malformed_yaml_raises(self):
        with pytest.raises(LoadError):
            load_task(FIXTURES / "malformed.yaml")

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_task(FIXTURES / "nonexistent.yaml")

    def test_validation_error_includes_path(self):
        with pytest.raises(SchemaValidationError) as exc_info:
            load_task(FIXTURES / "invalid_missing_source.yaml")
        assert "source" in str(exc_info.value)


class TestLoadTasksFromDir:
    """load_tasks_from_dir discovers all .yaml files and loads them."""

    @pytest.fixture
    def valid_dir(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir()
        (d / "valid_minimal.yaml").write_text(FIXTURES.joinpath("valid_minimal.yaml").read_text())
        return d

    def test_discovers_all_tasks(self, valid_dir):
        tasks = load_tasks_from_dir(valid_dir)
        assert len(tasks) == 1
        assert tasks[0].name == "rg_trait_implementors"

    def test_empty_dir_returns_empty_list(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        tasks = load_tasks_from_dir(d)
        assert tasks == []

    def test_skips_non_yaml(self, tmp_path):
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "task.yaml").write_text(FIXTURES.joinpath("valid_minimal.yaml").read_text())
        (d / "README.md").write_text("docs")
        tasks = load_tasks_from_dir(d)
        assert len(tasks) == 1
