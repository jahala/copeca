"""Test the tilth-to-copeca migration script.

These tests use a synthetic fixture that mimics tilth's benchmark/config.py
structure, so they work even when the real tilth repository is not accessible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def tilth_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create a synthetic tilth benchmark with 2 tasks."""
    tilth_dir = tmp_path / "tilth-fake"
    tilth_dir.mkdir()
    benchmark_dir = tilth_dir / "benchmark"
    benchmark_dir.mkdir()

    config_py = benchmark_dir / "config.py"
    config_py.write_text(
        """
TASKS = {
    "rg_trait_implementors": {
        "name": "rg_trait_implementors",
        "prompt": (
            "Find the Matcher trait definition and list"
            " all implementors in the ripgrep codebase."
        ),
        "repo": "ripgrep",
        "type": "comprehension",
        "language": "rust",
        "difficulty": "hard",
        "ground_truth": {
            "required_strings": ["Matcher", "find_at"],
            "all_of": [],
            "forbidden_strings": [],
        },
        "mutations": [],
        "test_command": [],
    },
    "rg_edit_line_count": {
        "name": "rg_edit_line_count",
        "prompt": "Fix the off-by-one bug in ripgrep's line counting.",
        "repo": "ripgrep",
        "type": "edit",
        "language": "rust",
        "difficulty": "medium",
        "ground_truth": {
            "required_strings": [],
            "all_of": [],
            "forbidden_strings": [],
        },
        "mutations": [
            {
                "file": "crates/searcher/src/lines.rs",
                "find": "count() as u64",
                "replace": "count() as u64 + 1",
            }
        ],
        "test_command": ["cargo", "test", "line_count"],
    },
}
REPOS = {
    "ripgrep": {
        "url": "https://github.com/BurntSushi/ripgrep.git",
        "commit": "0a88cccd5188074de96f54a4b6b44a63971ac157",
        "language": "rust",
        "toolchain": {"rust": "1.80.0"},
        "setup_command": ["cargo", "fetch"],
    },
}
    """
    )
    (benchmark_dir / "__init__.py").write_text("")
    return tilth_dir, benchmark_dir


# ── Helper ─────────────────────────────────────────────────────────────────────


def _migrate_script() -> Path:
    """Return the path to the migration script."""
    return Path(__file__).resolve().parent.parent.parent / "scripts" / "migrate_from_tilth.py"


def _run_migrate(tilth_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the migration script as a subprocess and return the result."""
    return subprocess.run(
        [
            sys.executable,
            str(_migrate_script()),
            "--tilth-path",
            str(tilth_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _read_yaml_files(output_dir: Path) -> list[dict]:
    """Read all YAML files from the output directory."""
    files = sorted(output_dir.rglob("*.yaml"))
    result = []
    for f in files:
        with open(f) as fh:
            result.append(yaml.safe_load(fh))
    return result


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestMigrationProducesYamlFiles:
    """Migration produces the expected number of YAML files."""

    def test_produces_two_files(self, tilth_fixture: tuple[Path, Path]):
        tilth_dir, _ = tilth_fixture
        output_dir = tilth_dir / "output"

        result = _run_migrate(tilth_dir, output_dir)

        assert result.returncode == 0, f"Migration failed: {result.stderr}"

        yaml_files = list(output_dir.rglob("*.yaml"))
        assert len(yaml_files) == 2, f"Expected 2 YAML files, got {len(yaml_files)}"
        assert "Done. Total: 2, migrated: 2, skipped: 0" in result.stdout


class TestComprehensionTaskYamlValid:
    """Comprehension task output has required_strings and correct type."""

    def test_comprehension_task_structure(self, tilth_fixture: tuple[Path, Path]):
        tilth_dir, _ = tilth_fixture
        output_dir = tilth_dir / "output"

        _run_migrate(tilth_dir, output_dir)

        # Find the comprehension task
        tasks = _read_yaml_files(output_dir)
        comp_task = next((t for t in tasks if t["type"] == "comprehension"), None)
        assert comp_task is not None, "No comprehension task found"

        assert comp_task["name"] == "rg_trait_implementors"
        assert comp_task["type"] == "comprehension"
        assert comp_task["category"] == "trace"  # find-trait-and-implementors = relational
        assert comp_task["language"] == "rust"
        assert comp_task["difficulty"] == "hard"
        assert comp_task["version"] == 1

        gt = comp_task["ground_truth"]
        assert "required_strings" in gt
        assert "Matcher" in gt["required_strings"]
        assert "find_at" in gt["required_strings"]
        assert "all_of" in gt
        # No test_command in comprehension ground truth
        assert "test_command" not in gt


class TestEditTaskYamlValid:
    """Edit task output has mutations and test_command."""

    def test_edit_task_structure(self, tilth_fixture: tuple[Path, Path]):
        tilth_dir, _ = tilth_fixture
        output_dir = tilth_dir / "output"

        _run_migrate(tilth_dir, output_dir)

        tasks = _read_yaml_files(output_dir)
        edit_task = next((t for t in tasks if t["type"] == "edit"), None)
        assert edit_task is not None, "No edit task found"

        assert edit_task["name"] == "rg_edit_line_count"
        assert edit_task["type"] == "edit"
        assert edit_task["category"] == "fix"
        assert edit_task["language"] == "rust"
        assert edit_task["difficulty"] == "medium"
        assert edit_task["version"] == 1

        gt = edit_task["ground_truth"]
        assert "test_command" in gt
        assert gt["test_command"] == ["cargo", "test", "line_count"]

        assert "mutations" in edit_task
        assert len(edit_task["mutations"]) == 1
        m = edit_task["mutations"][0]
        assert m["file"] == "crates/searcher/src/lines.rs"
        assert m["find"] == "count() as u64"
        assert m["replace"] == "count() as u64 + 1"


class TestOutputFilesPassCopecaValidate:
    """Each output file passes copeca validate."""

    def test_validate_passes_on_output(self, tilth_fixture: tuple[Path, Path]):
        tilth_dir, _ = tilth_fixture
        output_dir = tilth_dir / "output"

        _run_migrate(tilth_dir, output_dir)

        result = subprocess.run(
            ["copeca", "validate", str(output_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"copeca validate failed (exit {result.returncode}):\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


class TestSourceFieldIsSet:
    """Every output has source: 'tilth-benchmark (MIT)'."""

    def test_source_field(self, tilth_fixture: tuple[Path, Path]):
        tilth_dir, _ = tilth_fixture
        output_dir = tilth_dir / "output"

        _run_migrate(tilth_dir, output_dir)

        tasks = _read_yaml_files(output_dir)
        assert len(tasks) > 0, "No tasks produced"

        for t in tasks:
            expected = "tilth-benchmark (MIT)"
            msg = f"Task {t.get('name')}: expected source={expected!r}, got {t.get('source')!r}"
            assert t["source"] == expected, msg
