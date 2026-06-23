"""Tests for ISO-2: profile-based isolation — private HOME (API-KEY) vs host HOME
(SUBSCRIPTION) per arm (architecture §13.2).

Profile selection:
  API-KEY profile  — api_key_env IS set AND the named var is present in the host env:
                     private throwaway HOME; key passes through to the agent.
  SUBSCRIPTION profile — api_key_env absent OR named var not in host env (default):
                     host HOME unchanged; all provider keys dropped from child env;
                     Lock 2 (trace gate) guarantees A/B validity.
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
    This test uses the API-KEY profile (key present) to trigger private-HOME creation.
    """

    def test_setup_failure_leaves_no_private_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="indexed", setup=["false"])  # `false` exits 1 → RuntimeError

        pattern = str(Path(tempfile.gettempdir()) / "copeca-home-*")
        before = set(glob.glob(pattern))

        with pytest.raises(RuntimeError):
            provision_arm(
                mode,
                worktree,
                isolation=_isolation(api_key_env="ANTHROPIC_API_KEY"),
            )

        assert set(glob.glob(pattern)) == before, (
            "a failing setup must not leak a private HOME temp dir"
        )


# ── API-KEY profile: private HOME ────────────────────────────────────────────


class TestApiKeyProfilePrivateHome:
    """When api_key_env is set AND present in the host env, provision_arm creates
    a private throwaway HOME — the API-KEY profile (architecture §13.2).
    """

    def test_api_key_profile_home_is_not_host_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The HOME in the returned env must differ from the host HOME."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            config_home_env="CLAUDE_CONFIG_DIR",
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        host_home = os.environ.get("HOME", "")
        assert harness.env.get("HOME") != host_home, (
            "API-KEY profile: HOME must NOT be the host HOME"
        )

    def test_api_key_profile_home_is_a_real_empty_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The private HOME must exist and be empty (no host config bleed-in)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.env["HOME"])
        assert private_home.is_dir(), "API-KEY profile: private HOME must be an existing directory"
        assert list(private_home.iterdir()) == [], "API-KEY profile: private HOME must be empty"

    def test_api_key_profile_home_outside_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The private HOME must NOT be inside the worktree."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.env["HOME"])
        assert not private_home.is_relative_to(worktree), (
            "API-KEY profile: private HOME must not be nested inside the worktree"
        )

    def test_api_key_profile_returns_private_home_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ArmHarness.private_home must be set so the caller can tear it down."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.private_home is not None, (
            "API-KEY profile: ArmHarness.private_home must be set for teardown"
        )
        assert Path(harness.private_home).is_dir()

    def test_api_key_profile_exclude_keys_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API-KEY profile: key is wanted in the child env → exclude_keys must be empty."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.exclude_keys == set(), "API-KEY profile must not exclude any env keys"


# ── SUBSCRIPTION profile ──────────────────────────────────────────────────────


class TestSubscriptionProfile:
    """When api_key_env is absent (or not in host env), provision_arm uses the
    SUBSCRIPTION profile: no private HOME, host login, provider keys dropped.
    """

    def test_subscription_profile_no_private_home(self, tmp_path: Path) -> None:
        """SUBSCRIPTION profile must not create a private HOME."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()  # api_key_env=None → always subscription

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.private_home is None, "SUBSCRIPTION profile must not create a private HOME"

    def test_subscription_profile_host_home_unchanged(self, tmp_path: Path) -> None:
        """SUBSCRIPTION profile must NOT redirect HOME in the returned env."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation()  # api_key_env=None

        host_home = os.environ.get("HOME", "")
        harness = provision_arm(mode, worktree, isolation=isolation)

        env_home = harness.env.get("HOME")
        assert env_home is None or env_home == host_home, (
            "SUBSCRIPTION profile must not redirect HOME away from the host"
        )

    def test_subscription_profile_key_absent_from_host_is_subscription(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api_key_env named but NOT in host env → SUBSCRIPTION profile (no raise)."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert isinstance(harness, ArmHarness)
        assert harness.private_home is None, (
            "When api_key_env names a var absent from the host, SUBSCRIPTION profile applies"
        )

    def test_subscription_profile_excludes_provider_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SUBSCRIPTION profile must populate exclude_keys with provider key names."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert "ANTHROPIC_API_KEY" in harness.exclude_keys, (
            "SUBSCRIPTION profile must add ANTHROPIC_API_KEY to exclude_keys"
        )

    def test_subscription_profile_excludes_all_provider_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SUBSCRIPTION profile drops ALL provider keys, not just the named one."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            assert key in harness.exclude_keys, (
                f"SUBSCRIPTION profile must include {key!r} in exclude_keys"
            )

    def test_subscription_profile_sets_disable_env(self, tmp_path: Path) -> None:
        """SUBSCRIPTION profile still applies disable_ambient_env and disable_telemetry_env."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
            disable_telemetry_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1", (
            "disable_ambient_env must appear in SUBSCRIPTION arm env"
        )
        assert harness.env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1", (
            "disable_telemetry_env must appear in SUBSCRIPTION arm env"
        )


# ── config_home_env injection — API-KEY profile ───────────────────────────────


class TestConfigHomeEnv:
    """When isolation.config_home_env is set, that var must also point at the
    private home (API-KEY profile) so the CLI resolves its own config paths there."""

    def test_config_home_env_set_to_private_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            config_home_env="CLAUDE_CONFIG_DIR",
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = harness.env["HOME"]
        assert harness.env.get("CLAUDE_CONFIG_DIR") == private_home, (
            "CLAUDE_CONFIG_DIR must equal the private HOME "
            "when config_home_env is set (API-KEY profile)"
        )

    def test_config_home_env_absent_when_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If IsolationSpec has no config_home_env, no extra var is injected."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")  # config_home_env=None

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert "CLAUDE_CONFIG_DIR" not in harness.env
        assert "CODEX_HOME" not in harness.env


# ── disable_ambient_env + disable_telemetry_env — both profiles ───────────────


class TestDisableEnvMerge:
    """disable_ambient_env and disable_telemetry_env from IsolationSpec must
    appear in the harness env for every arm, in both profiles."""

    def test_disable_ambient_env_in_api_key_harness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1", (
            "disable_ambient_env must appear in API-KEY arm env"
        )

    def test_disable_telemetry_env_in_api_key_harness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            disable_telemetry_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1", (
            "disable_telemetry_env must appear in API-KEY arm env"
        )

    def test_all_disable_envs_combined_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All isolation env vars appear together without clobbering each other (API-KEY)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            config_home_env="CLAUDE_CONFIG_DIR",
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
            disable_telemetry_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert "HOME" in harness.env
        assert harness.env.get("CLAUDE_CONFIG_DIR") == harness.env["HOME"]
        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
        assert harness.env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"

    def test_experimental_arm_also_gets_isolation_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Isolation env applies uniformly — experimental arm gets it too (API-KEY)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(
            name="tilth",
            env={"TOOL_ENDPOINT": "http://localhost:8080"},
        )
        isolation = _isolation(
            api_key_env="ANTHROPIC_API_KEY",
            disable_ambient_env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        )

        harness = provision_arm(mode, worktree, isolation=isolation)

        assert harness.env.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1"
        assert harness.env.get("TOOL_ENDPOINT") == "http://localhost:8080"


# ── Teardown — private_home is removable (API-KEY profile) ────────────────────


class TestPrivateHomeTeardown:
    """The private home directory (API-KEY profile) must be removable after the run."""

    def test_private_home_can_be_removed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode = _mode(name="baseline")
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(mode, worktree, isolation=isolation)

        private_home = Path(harness.private_home)  # type: ignore[arg-type]
        assert private_home.is_dir()
        shutil.rmtree(private_home)
        assert not private_home.exists(), (
            "API-KEY profile: private HOME must be removable after teardown"
        )

    def test_two_arms_get_distinct_private_homes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two provision_arm calls in API-KEY profile must produce different private HOME dirs."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        mode_a = _mode(name="baseline")
        mode_b = _mode(name="tilth", env={"TOOL": "x"})
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness_a = provision_arm(mode_a, worktree, arm_name="baseline", isolation=isolation)
        harness_b = provision_arm(mode_b, worktree, arm_name="tilth", isolation=isolation)

        assert harness_a.env["HOME"] != harness_b.env["HOME"], (
            "Each API-KEY arm must get its own private HOME"
        )


# ── Profile auto-selection ────────────────────────────────────────────────────


class TestProfileAutoSelection:
    """Profile is selected by checking whether the named key var is in the host env."""

    def test_api_key_profile_selected_when_key_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(_mode(name="baseline"), worktree, isolation=isolation)

        assert harness.private_home is not None, "API-KEY profile: private_home must be set"
        assert harness.exclude_keys == set(), "API-KEY profile: exclude_keys must be empty"

    def test_subscription_profile_selected_when_key_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        isolation = _isolation(api_key_env="ANTHROPIC_API_KEY")

        harness = provision_arm(_mode(name="baseline"), worktree, isolation=isolation)

        assert harness.private_home is None, "SUBSCRIPTION profile: private_home must be None"
        assert len(harness.exclude_keys) > 0, "SUBSCRIPTION profile: exclude_keys must be populated"

    def test_subscription_profile_when_api_key_env_is_none(self, tmp_path: Path) -> None:
        """api_key_env=None means no key var → always SUBSCRIPTION profile."""
        worktree = tmp_path / "repo"
        worktree.mkdir()
        isolation = _isolation()  # api_key_env=None

        harness = provision_arm(_mode(name="baseline"), worktree, isolation=isolation)

        assert harness.private_home is None, (
            "api_key_env=None → SUBSCRIPTION profile → no private HOME"
        )
