"""Test `copeca verify --batch` CLI command.

Tests verify completeness checking: all expected (task, mode, model, rep) identities
present in a directory vs. a scenario spec.  Single-artifact path is unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from copeca.results.artifact import build_artifact


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _make_artifact(
    output_dir: Path,
    worktree: Path,
    *,
    task: str,
    mode: str,
    model: str,
    repetition: int,
) -> Path:
    """Build a valid .copeca zip for the given identity."""
    record = {"task": task, "mode": mode, "model": model, "repetition": repetition}
    return build_artifact(record, worktree, output_dir)


def _write_scenario(
    path: Path, tasks: list[str], modes: list[str], models: list[str], repetitions: int
) -> None:
    """Write a minimal scenario YAML to path."""
    tasks_str = ", ".join(f'"{t}"' for t in tasks)
    modes_str = ", ".join(f'"{m}"' for m in modes)
    models_str = ", ".join(f'"{m}"' for m in models)
    path.write_text(
        f"name: testscenario\n"
        f"tasks: [{tasks_str}]\n"
        f"modes: [{modes_str}]\n"
        f"models: [{models_str}]\n"
        f"repetitions: {repetitions}\n"
    )


class TestVerifyBatchCLI:
    """CLI integration tests for `copeca verify --batch`."""

    def test_batch_incomplete_exits_nonzero_and_names_missing(self, tmp_path: Path) -> None:
        """Missing rep exits 1 and prints the missing identity."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        # Only rep00 is present; scenario expects 2 reps
        _make_artifact(
            output_dir, worktree, task="mytask", mode="baseline", model="mymodel", repetition=0
        )

        scenario_path = tmp_path / "scenario.yaml"
        _write_scenario(
            scenario_path, tasks=["mytask"], modes=["baseline"], models=["mymodel"], repetitions=2
        )

        result = copeca("verify", "--batch", str(output_dir), "--scenario", str(scenario_path))

        assert result.returncode != 0, (
            f"Expected non-zero exit for incomplete batch.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        combined = result.stdout + result.stderr
        # Must name the missing run
        assert "mytask" in combined, f"Missing task not named.\n{combined}"
        assert "rep01" in combined or "repetition" in combined.lower(), (
            f"Missing rep not named.\n{combined}"
        )

    def test_batch_complete_exits_zero(self, tmp_path: Path) -> None:
        """All expected reps present → exits 0."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        for rep in range(2):
            _make_artifact(
                output_dir,
                worktree,
                task="mytask",
                mode="baseline",
                model="mymodel",
                repetition=rep,
            )

        scenario_path = tmp_path / "scenario.yaml"
        _write_scenario(
            scenario_path, tasks=["mytask"], modes=["baseline"], models=["mymodel"], repetitions=2
        )

        result = copeca("verify", "--batch", str(output_dir), "--scenario", str(scenario_path))

        assert result.returncode == 0, (
            f"Expected zero exit for complete batch.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_batch_missing_scenario_flag_errors(self, tmp_path: Path) -> None:
        """--batch without --scenario must fail (scenario is required for identity check)."""
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        result = copeca("verify", "--batch", str(output_dir))

        assert result.returncode != 0, (
            f"Expected non-zero exit when --scenario is missing.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_batch_empty_dir_exits_nonzero(self, tmp_path: Path) -> None:
        """Empty artifact dir with a non-empty scenario exits non-zero."""
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        scenario_path = tmp_path / "scenario.yaml"
        _write_scenario(
            scenario_path, tasks=["t1"], modes=["baseline"], models=["m"], repetitions=1
        )

        result = copeca("verify", "--batch", str(output_dir), "--scenario", str(scenario_path))

        assert result.returncode != 0, (
            f"Expected non-zero exit for empty dir.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_single_artifact_path_unchanged(self, tmp_path: Path) -> None:
        """The original single-artifact verify path still works (no regression)."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        artifact = build_artifact(record, worktree, output_dir)

        result = copeca("verify", str(artifact))

        assert result.returncode == 0, (
            f"Single-artifact verify must still work.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
