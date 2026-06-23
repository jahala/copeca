"""ISO-8: Version provenance — tool_version, tool_path, cli_version, tool_under_test in records.

Architecture: I/O helpers live in validation.py (orchestration edge).
contamination.py stays pure (no I/O).

Engineering.md §6: failing test first; §5: reproducibility — every run records
the resolved tool version + path so "which version was tested?" is always
answerable from the artifact.
"""

import logging
import stat
from pathlib import Path

import pytest

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    IsolationSpec,
    Language,
    Mode,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.orchestration.validation import (
    detect_multi_version_installs,
    resolve_cli_version,
    resolve_tool_version,
)
from copeca.runners.parsers.base import RunResult

# ── Helpers shared across test classes ────────────────────────────────────────


def _make_stub_binary(path: Path, version_output: str) -> Path:
    """Write a tiny shell script that prints version_output and exits 0."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{version_output}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _task() -> Task:
    return Task(
        name="iso8_task",
        source="test",
        repo="test-repo",
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="ok",
        ground_truth=ComprehensionGroundTruth(required_strings=[]),
    )


class _StubRunner:
    """Minimal runner — no real subprocess, supports isolation attribute."""

    name = "stub"
    cli: str | None = None
    isolation: IsolationSpec | None = None

    def build_command(self, model: str, prompt: str, **kwargs: object) -> list[str]:
        return ["echo", "ok"]

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict | None = None,
        exclude: set[str] | None = None,
    ) -> RunResult:
        return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)


class _StubRepoMgr:
    def __init__(self, worktree: Path) -> None:
        self._wt = worktree

    def verify_toolchain(self, key: str) -> None:
        pass

    def create_worktree(self, *args: object, **kwargs: object) -> Path:
        self._wt.mkdir(parents=True, exist_ok=True)
        return self._wt

    def setup(self, wt: Path) -> None:
        pass

    def reset(self, wt: Path) -> None:
        pass

    def remove_worktree(self, wt: Path) -> None:
        pass


# ── Unit: resolve_tool_version ─────────────────────────────────────────────────


class TestResolveToolVersion:
    def test_returns_version_and_path_from_stub(self, tmp_path: Path) -> None:
        """resolve_tool_version runs <command> --version and returns first stdout line."""
        stub = _make_stub_binary(tmp_path / "tilth", "tilth 1.0.0")
        version, path = resolve_tool_version(str(stub))
        assert version == "tilth 1.0.0"
        assert path == str(stub)

    def test_nonexistent_command_returns_none_no_crash(self, tmp_path: Path) -> None:
        """Missing binary must NOT raise — returns (None, None)."""
        version, path = resolve_tool_version("/nonexistent/path/to/tilth_xyz_missing")
        assert version is None
        assert path is None

    def test_command_that_fails_returns_none(self, tmp_path: Path) -> None:
        """Script that exits non-zero → (None, None), no exception."""
        stub = tmp_path / "bad_tilth"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        version, path = resolve_tool_version(str(stub))
        assert version is None

    def test_strips_whitespace_from_version(self, tmp_path: Path) -> None:
        """Version output is stripped of leading/trailing whitespace."""
        stub = _make_stub_binary(tmp_path / "tilth", "  tilth 0.9.0  ")
        version, _ = resolve_tool_version(str(stub))
        assert version == "tilth 0.9.0"


# ── Unit: resolve_cli_version ──────────────────────────────────────────────────


class TestResolveCliVersion:
    def test_returns_version_from_version_cmd(self, tmp_path: Path) -> None:
        """Runs isolation.version_cmd and returns stripped first line."""
        stub = _make_stub_binary(tmp_path / "claude", "claude 1.2.3")
        spec = IsolationSpec(version_cmd=[str(stub)])
        version = resolve_cli_version(spec)
        assert version == "claude 1.2.3"

    def test_empty_version_cmd_returns_none(self) -> None:
        """IsolationSpec with no version_cmd returns None."""
        spec = IsolationSpec(version_cmd=[])
        version = resolve_cli_version(spec)
        assert version is None

    def test_none_isolation_returns_none(self) -> None:
        """None isolation spec returns None."""
        version = resolve_cli_version(None)
        assert version is None

    def test_nonexistent_binary_returns_none(self) -> None:
        """Bad binary in version_cmd → None, no exception."""
        spec = IsolationSpec(version_cmd=["/nonexistent/bin/claude_xyz_missing"])
        version = resolve_cli_version(spec)
        assert version is None


# ── Unit: detect_multi_version_installs ────────────────────────────────────────


class TestDetectMultiVersionInstalls:
    def test_no_warning_when_single_version(self, tmp_path: Path) -> None:
        """One binary at the configured path → exactly one finding, no warning logged."""
        bin_dir = tmp_path / "bin"
        stub = _make_stub_binary(bin_dir / "tilth", "tilth 1.0.0")
        findings = detect_multi_version_installs(
            configured_command=str(stub),
            binary_name="tilth",
            path_dirs=[str(bin_dir)],
        )
        # Single installation → one finding entry, no duplicate warning
        assert len(findings) == 1
        assert findings[0][0] == str(stub)
        assert findings[0][1] == "tilth 1.0.0"

    def test_warning_when_two_versions_on_path(self, tmp_path: Path) -> None:
        """Two stubs with different --version outputs → two findings returned."""
        dir1 = tmp_path / "cargo_bin"
        dir2 = tmp_path / "homebrew_bin"
        stub1 = _make_stub_binary(dir1 / "tilth", "tilth 1.0.0")
        stub2 = _make_stub_binary(dir2 / "tilth", "tilth 0.9.0")

        findings = detect_multi_version_installs(
            configured_command=str(stub1),
            binary_name="tilth",
            path_dirs=[str(dir1), str(dir2)],
        )
        # Should report 2 distinct installations
        assert len(findings) == 2
        paths = [f[0] for f in findings]
        assert str(stub1) in paths
        assert str(stub2) in paths

    def test_same_version_not_duplicated(self, tmp_path: Path) -> None:
        """Two binaries with identical version are still reported (different paths matter)."""
        dir1 = tmp_path / "a"
        dir2 = tmp_path / "b"
        stub1 = _make_stub_binary(dir1 / "tilth", "tilth 1.0.0")
        _make_stub_binary(dir2 / "tilth", "tilth 1.0.0")

        findings = detect_multi_version_installs(
            configured_command=str(stub1),
            binary_name="tilth",
            path_dirs=[str(dir1), str(dir2)],
        )
        # Both paths are distinct even if the version is the same
        assert len(findings) == 2

    def test_configured_not_on_path_still_included(self, tmp_path: Path) -> None:
        """The configured command is always included even if not on any PATH dir."""
        stub = _make_stub_binary(tmp_path / "private" / "tilth", "tilth 1.0.0")
        empty_dir = tmp_path / "empty_bin"
        empty_dir.mkdir()

        findings = detect_multi_version_installs(
            configured_command=str(stub),
            binary_name="tilth",
            path_dirs=[str(empty_dir)],
        )
        # Only the configured binary exists; single installation = no conflict
        assert len(findings) == 1

    def test_warns_via_logging(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """When 2+ installs are found, a logging.warning is emitted."""
        dir1 = tmp_path / "cargo"
        dir2 = tmp_path / "brew"
        _make_stub_binary(dir1 / "tilth", "tilth 1.0.0")
        _make_stub_binary(dir2 / "tilth", "tilth 0.9.0")

        with caplog.at_level(logging.WARNING, logger="copeca.orchestration.validation"):
            detect_multi_version_installs(
                configured_command=str(dir1 / "tilth"),
                binary_name="tilth",
                path_dirs=[str(dir1), str(dir2)],
            )

        assert any("tilth" in m for m in caplog.messages)


# ── Integration: record carries new provenance fields ─────────────────────────


class TestRecordVersionFields:
    """run_single builds JSONL records that carry the new ISO-8 provenance fields."""

    def test_non_baseline_carries_tool_version_and_path(self, tmp_path: Path) -> None:
        """A mode with mcp_config: record.tool_version + tool_path from the stub binary."""
        stub = _make_stub_binary(tmp_path / "bin" / "mytilth", "tilth 1.0.0")

        mode = Mode(
            name="tilth",
            description="test",
            mcp_config={
                "mcpServers": {
                    "tilth": {"command": str(stub), "args": ["--mcp"]},
                }
            },
        )

        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="tilth",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert record["tool_version"] == "tilth 1.0.0"
        assert record["tool_path"] == str(stub)

    def test_baseline_carries_none_for_tool_fields(self, tmp_path: Path) -> None:
        """Baseline (mode=None) → tool_version and tool_path are None."""
        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=None,
        )

        assert record["tool_version"] is None
        assert record["tool_path"] is None

    def test_cli_version_from_isolation_version_cmd(self, tmp_path: Path) -> None:
        """When runner.isolation.version_cmd is set, cli_version appears in the record."""
        stub = _make_stub_binary(tmp_path / "bin" / "claude", "claude 2.5.0")

        runner = _StubRunner()
        runner.isolation = IsolationSpec(version_cmd=[str(stub)])

        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
        )

        assert record["cli_version"] == "claude 2.5.0"

    def test_cli_version_none_when_no_version_cmd(self, tmp_path: Path) -> None:
        """No version_cmd on runner → cli_version is None."""
        runner = _StubRunner()
        runner.isolation = IsolationSpec(version_cmd=[])
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
        )

        assert record["cli_version"] is None

    def test_version_resolution_failure_returns_none_no_crash(self, tmp_path: Path) -> None:
        """Binary exists (passes tool-availability preflight) but --version exits 1.
        resolve_tool_version must NOT crash the run; tool_version is recorded as None.
        """
        # A stub that exists and is executable but exits 1 on --version
        stub = tmp_path / "bin" / "bad_tilth"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        mode = Mode(
            name="tilth",
            description="test",
            mcp_config={
                "mcpServers": {
                    "tilth": {
                        "command": str(stub),
                        "args": ["--mcp"],
                    }
                }
            },
        )

        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="tilth",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        # Version resolution fails (exit 1) but run completes and records None
        assert record["tool_version"] is None
        # tool_path may still be resolved even when --version fails
        assert "tool_path" in record

    def test_tool_under_test_from_mcp_config_keys(self, tmp_path: Path) -> None:
        """record.tool_under_test = ['mcp__<srv>__'] for each server in mcp_config."""
        stub = _make_stub_binary(tmp_path / "bin" / "mytilth", "tilth 1.0.0")

        mode = Mode(
            name="tilth",
            description="test",
            mcp_config={
                "mcpServers": {
                    "tilth": {"command": str(stub), "args": ["--mcp"]},
                }
            },
        )

        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="tilth",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert record["tool_under_test"] == ["mcp__tilth__"]

    def test_baseline_tool_under_test_is_none(self, tmp_path: Path) -> None:
        """Baseline (no mcp_config) → tool_under_test is None."""
        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=None,
        )

        assert record["tool_under_test"] is None
