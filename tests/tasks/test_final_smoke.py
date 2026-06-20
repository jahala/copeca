"""Final smoke tests for the copeca task corpus.

Tests:
1. test_smoke_validate — copeca validate tasks/ returns 0
2. test_smoke_list_shows_tasks — copeca list tasks/ shows task names
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from copeca.config.resources import data_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS_DIR = data_path("tasks")
COPECA = PROJECT_ROOT / ".venv" / "bin" / "copeca"


def _run_copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point."""
    return subprocess.run(
        [str(COPECA), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestSmokeValidate:
    """copeca validate tasks/ returns 0."""

    def test_smoke_validate(self):
        result = _run_copeca("validate", str(TASKS_DIR))
        assert result.returncode == 0, (
            f"copeca validate tasks/ failed (exit {result.returncode}):\n"
            f"stderr={result.stderr}\nstdout={result.stdout}"
        )


class TestSmokeList:
    """copeca list tasks/ shows task names."""

    def test_smoke_list_shows_tasks(self):
        result = _run_copeca("list", str(TASKS_DIR))
        assert result.returncode == 0, (
            f"copeca list tasks/ failed (exit {result.returncode}):\n"
            f"stderr={result.stderr}"
        )

        # The list output should contain known task names
        known_names = [
            "t001_find_matcher_trait",
            "t004_express_routing",
            "t002_fastapi_routing",
            "t003_gin_middleware",
        ]
        for name in known_names:
            assert name in result.stdout, (
                f"Expected task '{name}' in list output:\n{result.stdout}"
            )
