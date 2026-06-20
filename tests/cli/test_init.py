"""Test `copeca init` CLI command end-to-end."""

from __future__ import annotations

import subprocess
from pathlib import Path


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point and return CompletedProcess."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestInit:
    """copeca init bootstraps a working benchmark directory."""

    def test_init_creates_directory_structure(self, tmp_path: Path) -> None:
        """copeca init creates tasks/, defaults/, scenarios/, results/, repos.yaml."""
        target = tmp_path / "bench"
        result = copeca("init", str(target))
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert (target / "tasks").is_dir()
        assert (target / "defaults" / "runners").is_dir()
        assert (target / "defaults" / "modes").is_dir()
        assert (target / "scenarios").is_dir()
        assert (target / "results").is_dir()
        assert (target / "repos.yaml").exists()

    def test_init_copies_seed_tasks(self, tmp_path: Path) -> None:
        """copeca init copies task YAML files from the package corpus."""
        target = tmp_path / "bench"
        copeca("init", str(target))
        task_files = list(target.rglob("tasks/**/*.yaml"))
        assert len(task_files) >= 1, f"Expected at least 1 task file, got {len(task_files)}"

    def test_init_copies_repos_yaml(self, tmp_path: Path) -> None:
        """copeca init copies repos.yaml with known repo entries."""
        target = tmp_path / "bench"
        copeca("init", str(target))
        content = (target / "repos.yaml").read_text()
        assert "ripgrep" in content

    def test_init_validates_after_init(self, tmp_path: Path) -> None:
        """Seed tasks pass copeca validate after init."""
        target = tmp_path / "bench"
        copeca("init", str(target))
        result = subprocess.run(
            ["copeca", "validate", str(target / "tasks")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_init_existing_dir_succeeds(self, tmp_path: Path) -> None:
        """copeca init on an existing directory still succeeds."""
        target = tmp_path / "bench"
        target.mkdir()
        (target / "existing.txt").write_text("already here")
        result = copeca("init", str(target))
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_init_output_shows_summary(self, tmp_path: Path) -> None:
        """copeca init prints a summary of what was created."""
        target = tmp_path / "bench"
        result = copeca("init", str(target))
        out = result.stdout.lower()
        assert "tasks" in out
        assert "repos.yaml" in out or "repos" in out


class TestInitChain:
    """End-to-end chain: init -> validate -> list."""

    def test_init_then_validate_then_list(self, tmp_path: Path) -> None:
        """Full chain: init -> validate -> list works end-to-end."""
        target = tmp_path / "bench"
        copeca("init", str(target))
        v = copeca("validate", str(target / "tasks"))
        assert v.returncode == 0, f"validate stderr={v.stderr}"
        l = copeca("list", str(target / "tasks"))
        assert l.returncode == 0, f"list stderr={l.stderr}"
        assert "comprehension" in l.stdout or "edit" in l.stdout
