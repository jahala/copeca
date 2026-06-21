"""Test `copeca compare` CLI command end-to-end."""

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


class TestCompareCli:
    """copeca compare compares two JSONL result files."""

    def test_compare_two_valid_files_exits_zero(self, tmp_path: Path) -> None:
        """Comparing two valid JSONL files prints task names and exits 0."""
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        a.write_text('{"task":"t","correct":true,"total_cost_usd":0.05,"mode":"v1"}\n')
        b.write_text('{"task":"t","correct":true,"total_cost_usd":0.03,"mode":"v2"}\n')
        result = copeca("compare", str(a), str(b))
        assert result.returncode == 0
        assert "t" in result.stdout

    def test_compare_missing_before_exits_two(self, tmp_path: Path) -> None:
        """Missing 'before' file exits with code 2."""
        result = copeca("compare", str(tmp_path / "nope.jsonl"), str(tmp_path / "also.jsonl"))
        assert result.returncode == 2

    def test_compare_missing_after_exits_two(self, tmp_path: Path) -> None:
        """Missing 'after' file exits with code 2."""
        a = tmp_path / "a.jsonl"
        a.write_text('{"task":"t","correct":true,"total_cost_usd":0.05,"mode":"v1"}\n')
        result = copeca("compare", str(a), str(tmp_path / "nope.jsonl"))
        assert result.returncode == 2
