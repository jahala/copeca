"""Tests for ISO-2: private throwaway HOME per arm (architecture §13.2).

Every arm — baseline included — must get its own private HOME so the agent
never reads or writes the host's ~/.claude.json / ~/.codex / ~/.gemini.
"""

from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path

import pytest

from copeca.config.models import IsolationSpec, Mode
from copeca.orchestration.state import ArmHarness, provision_arm

# ── Helpers ───────────────────────────────────────────────────────────────────


def _mode(**kwargs: object) -> Mode:
    """Minimal valid Mode — tools list satisfies 'at least one path' validator."""
    defaults: dict[str, object] = {
        "name": "test_mode",
        "description": "test",
        "tools": ["Bash", "Read"],
    }
    defaults.update(kwargs)
    return Mode(**defaults)  # type: ignore[arg-type]


def _isolation(**kwargs: object) -> IsolationSpec:
    return IsolationSpec(**kwargs)  # type: ignore[arg-type]


# ── Cleanup on failure ────────────────────────────────────────────────────────


class TestProvisionArmFailureCleanup:
    """A failure inside provision_arm must not leak the private HOME temp dir.

    The private HOME is created AFTER the fallible integration-path work
    (agent_config copy, setup commands). run_single's finally only removes a
    home it receives on the returned harness, so a home created before a raise
    would orphan — hence creation must come last.
    """

    def test_setup_failure_leaves_no_private_home(self, tmp_path: Path) -> None:
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="indexed", setup=["false"])  # `false` exits 1 → RuntimeError

        pattern = str(Path(tempfile.gettempdir()) / "copeca-home-*")
        before = set(glob.glob(pattern))

        with pytest.raises(RuntimeError):
            provision_arm(mode, worktree, isolation=_isolation())

        assert set(glob.glob(pattern)) == before, (
            "a failing setup must not leak a private HOME temp dir"
        )


# ── Private HOME — baseline arm ───────────────────────────────────────────────


class TestBaselinePrivateHome:
    """provision_arm must give baseline the same private HOME treatment as any
    experimental arm — the old empty-ArmHarness short-circuit is the bug we fix.
    """

    def test_baseline_home_is_not_host_home(self, tmp_path: Path) -> None:
        """The HOME in the returned env must differ from the host HOME."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(config_home_env="CLAUDE_CONFIG_DIR")

        harness = provision_arm(mode, worktree, isolation=isolation)

        host_home = os.environ.get("HOME", "")
        assert harness.env.get("HOME") != host_home, "baseline arm HOME must NOT be the host HOME"

    def test_baseline_home_is_a_real_empty_directory(self, tmp_path: Path) -> None:
        """The private HOME must exist and be empty (no host config bleed-in)."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.env["HOME"])
        assert private_home.is_dir(), "private HOME must be an existing directory"
        assert list(private_home.iterdir()) == [], "private HOME must be empty"

    def test_baseline_home_outside_worktree(self, tmp_path: Path) -> None:
        """The private HOME must NOT be inside the worktree — it must not appear
        as an untracked file when the agent scans the working tree."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.env["HOME"])
        assert not private_home.is_relative_to(worktree), (
            "private HOME must not be nested inside the worktree"
        )

    def test_baseline_returns_private_home_path(self, tmp_path: Path) -> None:
        """ArmHarness.private_home must be set so the caller can tear it down."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.private_home is not None, "ArmHarness.private_home must be set for teardown"
        assert Path(harness.private_home).is_dir()


# ── config_home_env injection ─────────────────────────────────────────────────


class TestConfigHomeEnv:
    """When isolation.config_home_env is set, that var must also point at the
    private home so the CLI resolves its own config paths there too."""

    def test_config_home_env_set_to_private_home(self, tmp_path: Path) -> None:
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(config_home_env="CLAUDE_CONFIG_DIR")

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = harness.env["HOME"]
        assert harness.env.get("CLAUDE_CONFIG_DIR") == private_home, (
            "CLAUDE_CONFIG_DIR must equal the private HOME when config_home_env is set"
        )

    def test_config_home_env_absent_when_not_set(self, tmp_path: Path) -> None:
        """If IsolationSpec has no config_home_env, no extra var is injected."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()  # config_home_env=None

        harness = provision_arm(mode, worktree, isolation=isolation)

        # HOME is always set; other config-home vars should not appear
        assert "CLAUDE_CONFIG_DIR" not in harness.env
        assert "CODEX_HOME" not in harness.env


# ── disable_ambient_env + disable_telemetry_env ───────────────────────────────


class TestDisableEnvMerge:
    """disable_ambient_env and disable_telemetry_env from IsolationSpec must
    appear in the harness env for every arm."""

    def test_disable_ambient_env_in_baseline_harness(self, tmp_path: Path) -> None:
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1", (
            "disable_ambient_env must appear in baseline arm env"
        )

    def test_disable_telemetry_env_in_baseline_harness(self, tmp_path: Path) -> None:
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            disable_telemetry_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1", (
            "disable_telemetry_env must appear in baseline arm env"
        )

    def test_all_disable_envs_combined(self, tmp_path: Path) -> None:
        """All isolation env vars appear together without clobbering each other."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            config_home_env="CLAUDE_CONFIG_DIR",
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
            disable_telemetry_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert "HOME" in harness.env
        assert harness.env.get("CLAUDE_CONFIG_DIR") == harness.env["HOME"]
        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
        assert harness.env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"

    def test_experimental_arm_also_gets_isolation_env(self, tmp_path: Path) -> None:
        """Isolation env applies uniformly — experimental arm gets it too."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(
            name="tilth",
            env={"TOOL_ENDPOINT": "http://localhost:8080"},
        )
        isolation = _isolation(
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
        assert harness.env.get("TOOL_ENDPOINT") == "http://localhost:8080"


# ── Teardown — private_home is removable ──────────────────────────────────────


class TestPrivateHomeTeardown:
    """The private home directory must be removable after the run."""

    def test_private_home_can_be_removed(self, tmp_path: Path) -> None:
        import shutil

        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.private_home)  # type: ignore[arg-type]
        assert private_home.is_dir()
        shutil.rmtree(private_home)
        assert not private_home.exists(), "private HOME must be removable after teardown"

    def test_two_arms_get_distinct_private_homes(self, tmp_path: Path) -> None:
        """Two provision_arm calls must produce different private HOME dirs."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode_a = _mode(name="baseline")
        mode_b = _mode(name="tilth", env={"TOOL": "x"})
        isolation = _isolation()

        harness_a = provision_arm(mode_a, worktree, arm_name="baseline", isolation=isolation)
        harness_b = provision_arm(mode_b, worktree, arm_name="tilth", isolation=isolation)

        assert harness_a.env["HOME"] != harness_b.env["HOME"], (
            "Each arm must get its own private HOME"
        )


# ── API-key preflight ─────────────────────────────────────────────────────────


class TestApiKeyPreflight:
    """provision_arm must fail loudly when requires_api_key_env names a var
    that is absent from the calling process's environment.
    """

    def test_preflight_raises_when_api_key_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(requires_api_key_env="ANTHROPIC_API_KEY")

        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            provision_arm(mode, worktree, isolation=isolation)

    def test_preflight_passes_when_api_key_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(requires_api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert isinstance(harness, ArmHarness)

    def test_preflight_skipped_when_requires_api_key_env_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When isolation.requires_api_key_env is None, no preflight runs."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()  # requires_api_key_env=None

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert isinstance(harness, ArmHarness)

    def test_preflight_error_message_names_the_missing_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(requires_api_key_env="OPENAI_API_KEY")

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            provision_arm(mode, worktree, isolation=isolation)
