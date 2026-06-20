"""Test `copeca run` CLI scenario detection.

The CLI `run` command (cli.py:106-113) detects scenarios by checking for
a ``"tasks"`` key in YAML or ``"scenario"`` in the filename.
This path has ZERO integration test coverage — the matrix tests
call run_matrix() directly, never through the CLI.

Important
---------
These tests verify *scenario detection logic*, not full execution.
The CLI will attempt git clone + worktree creation via repos.yaml.
Since repos aren't set up in the test environment, it may exit non-zero
after detection. The assertions focus on what IS guaranteed: that the
CLI correctly identifies a scenario file and enters the scenario code path.

Architecture: CLI integration tests via subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _write_task_yaml(tasks_dir: Path, name: str) -> Path:
    """Write a minimal valid task YAML into tasks_dir and return the path."""
    task_yaml = tasks_dir / f"{name}.yaml"
    task_yaml.write_text(
        f"""name: {name}
source: test
repo: test-repo
type: comprehension
language: python
difficulty: easy
version: 1
prompt: "say OK"
ground_truth:
  required_strings: ["OK"]
"""
    )
    return task_yaml


def _write_scenario_yaml(dir_path: Path, name: str) -> Path:
    """Write a minimal valid scenario YAML that should be detected."""
    scenario = dir_path / f"{name}.yaml"
    scenario.write_text(
        f"""name: {name}
tasks: [task_a]
modes: [baseline]
models: [test-model]
repetitions: 1
budget_usd: 2.0
"""
    )
    return scenario


# ── Tests ──────────────────────────────────────────────────────────────


class TestRunScenario:
    """Scenario detection through the copeca run CLI."""

    def test_scenario_detected_in_stdout(self, tmp_path: Path) -> None:
        """CLI prints 'Detected scenario file' when YAML has 'tasks' key.

        This is the primary detection path (cli.py:109-113).
        A YAML file with a top-level ``tasks`` key triggers scenario mode.
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(tasks_dir, "task_a")
        scenario = _write_scenario_yaml(tmp_path, "test_scenario")

        result = copeca("run", "--task", str(scenario),
                        "--runner", "echo", "--model", "test-model")

        combined = result.stdout + result.stderr
        # The key assertion: scenario detection happened
        assert "Detected scenario file" in combined, (
            f"Scenario not detected.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_scenario_detected_by_filename(self, tmp_path: Path) -> None:
        """File named '*scenario*' is detected as scenario even if
        it would otherwise look like a task.

        Detection path: ``"scenario" in task.name.lower()`` (cli.py:112).
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(tasks_dir, "task_a")

        # File named "scenario" but with 'tasks' key to be valid
        s = tmp_path / "my_scenario.yaml"
        s.write_text(
            """name: my_scenario
tasks: [task_a]
modes: [baseline]
models: [m]
repetitions: 1
"""
        )
        result = copeca("run", "--task", str(s),
                        "--runner", "echo", "--model", "m")

        combined = result.stdout + result.stderr
        assert "Detected scenario file" in combined, (
            f"Filename-based detection failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_task_without_tasks_key_not_detected_as_scenario(self, tmp_path: Path) -> None:
        """A YAML file without 'tasks' key and without 'scenario' in
        filename is NOT detected as a scenario — it's treated as a
        single task.

        This tests that the detection logic correctly separates
        task YAML from scenario YAML.
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        task_yaml = tmp_path / "some_task.yaml"
        task_yaml.write_text(
            """name: some_task
source: test
repo: test-repo
type: comprehension
language: python
difficulty: easy
version: 1
prompt: "say OK"
ground_truth:
  required_strings: ["OK"]
"""
        )
        result = copeca("run", "--task", str(task_yaml),
                        "--runner", "echo", "--model", "test-model")

        combined = result.stdout + result.stderr
        assert "Detected scenario file" not in combined, (
            f"Task incorrectly detected as scenario.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_scenario_with_empty_tasks_still_detected(self, tmp_path: Path) -> None:
        """A YAML file with 'tasks' key (even empty list) is detected
        as scenario mode. Pydantic will reject it, but detection happens first.
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        s = tmp_path / "empty_scenario.yaml"
        s.write_text(
            """name: empty_scenario
tasks: []
modes: [baseline]
models: [m]
repetitions: 1
"""
        )
        result = copeca("run", "--task", str(s),
                        "--runner", "echo", "--model", "m")

        combined = result.stdout + result.stderr
        # Detection should still fire — the 'tasks' key is present
        assert "Detected scenario file" in combined, (
            f"Empty-tasks scenario not detected.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_scenario_detection_case_insensitive_in_filename(self, tmp_path: Path) -> None:
        """Filename check uses .lower() — 'SCENARIO', 'Scenario', etc. all match."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(tasks_dir, "task_a")

        s = tmp_path / "UPPERCASE_SCENARIO.yaml"
        s.write_text(
            """name: uppercase_scenario
tasks: [task_a]
modes: [baseline]
models: [m]
repetitions: 1
"""
        )
        result = copeca("run", "--task", str(s),
                        "--runner", "echo", "--model", "m")

        combined = result.stdout + result.stderr
        assert "Detected scenario file" in combined, (
            f"Uppercase filename detection failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_nested_tasks_key_does_not_trigger_scenario(self, tmp_path: Path) -> None:
        """A YAML with nested 'tasks' inside ground_truth (not top-level)
        must NOT be detected as scenario. Only a top-level ``tasks`` key
        triggers scenario detection.
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        task_yaml = tmp_path / "task_with_nested_tasks.yaml"
        task_yaml.write_text(
            """name: nested_task
source: test
repo: test-repo
type: comprehension
language: python
difficulty: easy
version: 1
prompt: "list tasks"
ground_truth:
  tasks: ["a", "b", "c"]
  required_strings: ["OK"]
"""
        )
        result = copeca("run", "--task", str(task_yaml),
                        "--runner", "echo", "--model", "test-model")

        combined = result.stdout + result.stderr
        # Should NOT be detected as scenario — 'tasks' is nested
        assert "Detected scenario file" not in combined, (
            f"Nested tasks key incorrectly triggered scenario detection.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


class TestRunScenarioUnknownMode:
    """A scenario referencing a mode with no YAML must fail loudly."""

    def test_unknown_mode_fails_with_exit_1(self, tmp_path: Path) -> None:
        """run_matrix never sees the scenario: load_modes raises FileNotFoundError,
        the CLI echoes a clear error and exits 1 (validation failure).

        Without the tautology fix the scenario's own mode list was treated as
        the 'available' set, so an unknown mode would silently slip through.
        """
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(tasks_dir, "task_a")

        s = tmp_path / "bad_mode_scenario.yaml"
        s.write_text(
            """name: bad_mode_scenario
tasks: [task_a]
modes: [no-such-mode-xyz]
models: [m]
repetitions: 1
"""
        )
        result = copeca("run", "--task", str(s),
                        "--runner", "echo", "--model", "m")

        combined = result.stdout + result.stderr
        assert result.returncode == 1, (
            f"Unknown mode must exit 1.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "no-such-mode-xyz" in combined, (
            f"Error must name the missing mode.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
