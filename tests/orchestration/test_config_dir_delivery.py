"""Test A — config-dir delivery to runner.run() via config_dir_env.

The mechanism: SubprocessRunner.config_dir_env names the env var that should
carry the per-arm config dir path.  run_single reads that attribute (via
getattr) and injects the var into the run env.

We assert the mechanism — the env-var NAME is whatever the spy declares, NOT
a hardcoded CLAUDE_* name.
"""

from __future__ import annotations

import json
from pathlib import Path

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Mode,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.runners.parsers.base import RunResult

# ── Spy runner — declares a config_dir_env attribute ─────────────────────────


class ConfigDirSpyRunner:
    """Spy that captures the env kwarg; exposes config_dir_env for the mechanism."""

    name: str = "spy-cfg"
    config_dir_env: str = "TEST_CFG_DIR"  # operator-declared name, NOT hardcoded

    def __init__(self) -> None:
        self.captured_env: dict[str, str] | None = None

    def build_command(self, model: str, prompt: str, **kwargs: object) -> list[str]:
        return ["echo", "ok"]

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        self.captured_env = dict(env) if env is not None else {}
        return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)


class NoConfigDirSpyRunner:
    """Spy without config_dir_env — simulates a runner that doesn't support it."""

    name: str = "spy-no-cfg"
    # No config_dir_env attribute at all

    def __init__(self) -> None:
        self.captured_env: dict[str, str] | None = None

    def build_command(self, model: str, prompt: str, **kwargs: object) -> list[str]:
        return ["echo", "ok"]

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        self.captured_env = dict(env) if env is not None else {}
        return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)


# ── Stub repo manager ─────────────────────────────────────────────────────────


class StubRepoMgr:
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


# ── Task helper ───────────────────────────────────────────────────────────────


def _task(name: str = "t") -> Task:
    return Task(
        name=name,
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


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestConfigDirDelivery:
    """config_dir_env mechanism: runner declares the var name, run_single injects it."""

    def test_config_dir_injected_when_runner_declares_env_var(self, tmp_path: Path) -> None:
        """When mode.agent_config is set AND runner has config_dir_env, that var
        must appear in the env passed to runner.run(), pointing at the per-arm
        config dir that provision_arm created.

        Key: we assert 'TEST_CFG_DIR' (the spy's declared name), NOT 'CLAUDE_CONFIG_DIR'.
        """
        settings = {"theme": "dark"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = Mode(
            name="cfgmode",
            agent_config=str(settings_file),
        )

        runner = ConfigDirSpyRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="cfgmode",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert runner.captured_env is not None, "runner.run() must receive env="
        assert "TEST_CFG_DIR" in runner.captured_env, (
            "config_dir_env='TEST_CFG_DIR' must be injected — "
            "this is a mechanism test, NOT a CLAUDE_* name test"
        )
        # The value must point at a real directory that was created
        cfg_path = Path(runner.captured_env["TEST_CFG_DIR"])
        assert cfg_path.is_dir(), (
            f"TEST_CFG_DIR must point at the per-arm config dir; got {cfg_path}"
        )

    def test_config_dir_absent_when_no_agent_config(self, tmp_path: Path) -> None:
        """Baseline mode (no agent_config) must NOT inject the config-dir env var,
        even if the runner declares config_dir_env.
        """
        mode = Mode(
            name="envonly",
            env={"SOME_KEY": "val"},  # has a path, but not agent_config
        )

        runner = ConfigDirSpyRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="envonly",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert runner.captured_env is not None
        assert "TEST_CFG_DIR" not in runner.captured_env, (
            "TEST_CFG_DIR must be absent when mode has no agent_config"
        )

    def test_config_dir_absent_when_runner_has_no_config_dir_env(self, tmp_path: Path) -> None:
        """When the runner has no config_dir_env attribute, nothing is injected —
        even if mode.agent_config is set.
        """
        settings = {"theme": "dark"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = Mode(
            name="cfgmode",
            agent_config=str(settings_file),
        )

        runner = NoConfigDirSpyRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="cfgmode",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert runner.captured_env is not None
        # No TEST_CFG_DIR and no CLAUDE_CONFIG_DIR — runner didn't declare one
        cfg_keys = [k for k in runner.captured_env if "CFG" in k or "CONFIG" in k]
        assert cfg_keys == [], (
            f"No config-dir env var expected when runner has no config_dir_env; got: {cfg_keys}"
        )

    def test_mode_none_baseline_no_config_dir_injected(self, tmp_path: Path) -> None:
        """mode=None (clean baseline) must not inject any config-dir var."""
        runner = ConfigDirSpyRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=None,
        )

        assert runner.captured_env is not None
        assert "TEST_CFG_DIR" not in runner.captured_env
