"""Test copeca YAML loader with schema validation.

Tests the two-layer validation: jsonschema (structural) + Pydantic (type safety).
"""

from pathlib import Path

import pytest

from copeca.config.loader import (
    LoadError,
    SchemaValidationError,
    load_mode,
    load_modes,
    load_task,
    load_tasks_from_dir,
)
from copeca.config.models import ComprehensionGroundTruth, Mode, Task, TaskType
from copeca.config.resources import data_path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tasks"
DEFAULT_MODES_DIR = data_path("defaults", "modes")


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


class TestLoadMode:
    """load_mode reads <dir>/<name>.yaml and constructs a Mode."""

    def test_load_mode_baseline_returns_mode(self):
        mode = load_mode("baseline", modes_dirs=[DEFAULT_MODES_DIR])
        assert isinstance(mode, Mode)
        assert mode.name == "baseline"

    def test_load_mode_default_dir_resolves_regardless_of_cwd(self, monkeypatch, tmp_path):
        """With no modes_dirs, load_mode resolves the packaged defaults/modes.

        The default anchors on the installed package (data_path), so it works
        from any working directory — not just a source checkout's repo root.
        """
        monkeypatch.chdir(tmp_path)
        mode = load_mode("baseline")
        assert mode.name == "baseline"

    def test_load_mode_missing_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_mode("does-not-exist-xyz", modes_dirs=[DEFAULT_MODES_DIR])

    def test_load_mode_first_existing_dir_wins(self, tmp_path):
        """When multiple dirs are given, the first containing <name>.yaml wins."""
        first = tmp_path / "first"
        first.mkdir()
        (first / "custom.yaml").write_text(
            "name: custom\ndescription: from first\ntools: [Bash]\n"
        )
        mode = load_mode("custom", modes_dirs=[first, DEFAULT_MODES_DIR])
        assert mode.name == "custom"
        assert mode.description == "from first"


class TestLoadModes:
    """load_modes returns a name -> Mode dict for a list of names."""

    def test_load_modes_returns_name_keyed_dict(self):
        modes = load_modes(["baseline", "gateway"], modes_dirs=[DEFAULT_MODES_DIR])
        assert set(modes) == {"baseline", "gateway"}
        assert modes["baseline"].name == "baseline"
        assert modes["gateway"].name == "gateway"

    def test_load_modes_unknown_mode_raises(self):
        """A scenario referencing a mode with no YAML must fail loudly."""
        with pytest.raises(FileNotFoundError):
            load_modes(["baseline", "no-such-mode-xyz"], modes_dirs=[DEFAULT_MODES_DIR])
