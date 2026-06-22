"""Test `copeca new-task` CLI command end-to-end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from copeca.config.models import Category


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via sys.executable -m copeca (environment-portable)."""
    return subprocess.run(
        [sys.executable, "-m", "copeca", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestNewTaskCommand:
    """copeca new-task scaffolds a valid, commented task YAML skeleton."""

    def test_creates_file(self, tmp_path: Path) -> None:
        """new-task writes the skeleton to the specified path."""
        out = tmp_path / "tasks" / "my_task.yaml"
        result = copeca("new-task", str(out))
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert out.exists()

    def test_output_is_parseable_yaml(self, tmp_path: Path) -> None:
        """The scaffolded file is valid YAML (parseable without errors)."""
        out = tmp_path / "my_task.yaml"
        copeca("new-task", str(out))
        content = out.read_text()
        # Must parse without exception
        doc = yaml.safe_load(content)
        assert isinstance(doc, dict), "Expected YAML mapping at top level"

    def test_required_fields_present(self, tmp_path: Path) -> None:
        """Skeleton contains every required Task field."""
        out = tmp_path / "my_task.yaml"
        copeca("new-task", str(out))
        doc = yaml.safe_load(out.read_text())
        required = {
            "name",
            "source",
            "repo",
            "type",
            "category",
            "language",
            "difficulty",
            "version",
            "prompt",
            "ground_truth",
        }
        missing = required - set(doc.keys())
        assert not missing, f"Skeleton missing required fields: {missing}"

    def test_all_current_categories_listed(self, tmp_path: Path) -> None:
        """Skeleton comment lists every current Category enum value."""
        out = tmp_path / "my_task.yaml"
        copeca("new-task", str(out))
        content = out.read_text()
        for category in Category:
            assert category.value in content, (
                f"Category '{category.value}' not found in skeleton — "
                "new-task must derive categories from the Category enum"
            )

    def test_refuses_to_overwrite_existing_file(self, tmp_path: Path) -> None:
        """new-task exits non-zero when the target file already exists."""
        out = tmp_path / "existing.yaml"
        out.write_text("already here\n")
        result = copeca("new-task", str(out))
        assert result.returncode != 0
        assert "already exists" in (result.stderr + result.stdout)

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """new-task creates intermediate directories when they do not exist."""
        out = tmp_path / "a" / "b" / "c" / "task.yaml"
        result = copeca("new-task", str(out))
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert out.exists()

    def test_help_shows_command(self) -> None:
        """copeca new-task --help exits 0 and describes the command."""
        result = copeca("new-task", "--help")
        assert result.returncode == 0
        assert "new-task" in result.stdout or "scaffold" in result.stdout.lower()

    def test_stdout_reports_path(self, tmp_path: Path) -> None:
        """new-task prints the created file path in its output."""
        out = tmp_path / "reported.yaml"
        result = copeca("new-task", str(out))
        assert result.returncode == 0
        assert str(out) in result.stdout
