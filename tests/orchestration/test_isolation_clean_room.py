"""ISO-9: Hermetic clean-room proof — baseline runs cannot see a planted host MCP config.

This test proves end-to-end that when a SENTINEL host config (a fake home dir
containing a config file that registers an MCP server) is present in the simulated
host HOME, a BASELINE run hands the agent a FRESH private HOME so the agent
CANNOT see the sentinel — for claude, codex, AND gemini.

Architecture: subprocess boundary only (engineering.md §6). The stub agent is a
real executable at the subprocess edge; copeca's own logic (provision_arm, isolation
descriptor, SubprocessRunner) is exercised with zero mocking of our own code.

Per-CLI assertions and which findings.md §7 uncertainty each closes:

  CLAUDE
    saw_host_sentinel == False  → closes §7 "Claude ~/.claude.json has no mcpServers
                                  on the bench host" — proves HOME redirect hides it.
    home != fake_host_home      → proves Lock 1 private-home redirect (§13.2).
    "--strict-mcp-config" in argv → proves ISO-2 strict-MCP flag is injected (§13.4).

  CODEX
    saw_host_sentinel == False  → closes §7 "Codex CODEX_HOME / AGENTS.md" — proves
                                  CODEX_HOME redirect hides ~/.codex/config.toml.
    home != fake_host_home      → proves Lock 1 private-home redirect (§13.2).
    "--ignore-user-config" in argv → proves ISO-2 strict-MCP flag is injected (§13.4).

  GEMINI
    saw_host_sentinel == False  → closes §7 "Gemini GEMINI_CLI_HOME/.gemini" — proves
                                  GEMINI_CLI_HOME redirect hides ~/.gemini/settings.json.
    home != fake_host_home      → proves Lock 1 private-home redirect (§13.2).
    gemini_cli_home != fake_home → proves config_home_env is redirected (no mcpServers
                                   in the fresh home → zero MCP servers loaded).

DISCRIMINATION CHECK (non-vacuous proof):
  Each sentinel file EXISTS in the fake host home before the run. A broken isolation
  (provision_arm forgetting to set HOME) would leave the child's HOME pointing at the
  fake_host_home, making os.path.exists("~/<sentinel>") return True → assertion 1
  fails. The proof is only meaningful because the sentinel is real.
"""

import json
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    IsolationSpec,
    Language,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.runners.subprocess import SubprocessRunner

# ── Sentinels per CLI ──────────────────────────────────────────────────────────
#
# Each entry: (relative path under the fake host HOME, which config-home env var
# the sentinel lives inside, a human-readable label).
#
# sentinel rel-path → the file that would be read if HOME weren't redirected.
# The CLI's config-home env var is verified to point AWAY from fake_host_home.

_SENTINELS: dict[str, tuple[str, str]] = {
    # cli: (sentinel_rel_path, config_home_env)
    "claude": (".claude.json", "CLAUDE_CONFIG_DIR"),
    "codex": (".codex/config.toml", "CODEX_HOME"),
    "gemini": (".gemini/settings.json", "GEMINI_CLI_HOME"),
}

# ── Shared fixture helpers ─────────────────────────────────────────────────────


def _make_stub_agent(tmp_path: Path, cli_name: str) -> Path:
    """Write a tiny Python probe agent and make it executable.

    The probe prints a JSON object to stdout describing what it can see in the
    process environment and exits 0. This is the "agent" for the clean-room test.

    Fields emitted:
      home              — the HOME env var the child sees
      config_home_var   — the value of the CLI's config-home env var
      argv              — sys.argv[1:] (all flags copeca sent)
      saw_host_sentinel — True if ~/.<sentinel> exists from the child's perspective
    """
    # One probe per CLI so each can check the right sentinel and config var.
    sentinel_rel = _SENTINELS[cli_name][0]
    config_home_env = _SENTINELS[cli_name][1]

    source = textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, os, sys
        home = os.environ.get("HOME", "")
        config_home_var = os.environ.get({config_home_env!r}, "")
        sentinel_abs = os.path.join(home, {sentinel_rel!r})
        print(json.dumps({{
            "home": home,
            "config_home_var": config_home_var,
            "argv": sys.argv[1:],
            "saw_host_sentinel": os.path.exists(sentinel_abs),
        }}))
    """)
    tmp_path.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / f"stub_{cli_name}"
    stub.write_text(source)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _make_sentinel(fake_home: Path, cli_name: str) -> Path:
    """Create the sentinel file under fake_home so the proof is non-vacuous.

    DISCRIMINATION PROOF: the sentinel MUST exist before the run so that a broken
    isolation (no HOME redirect) would cause saw_host_sentinel == True. We assert
    the file exists here; the test then asserts saw_host_sentinel == False — meaning
    the isolation redirect worked.
    """
    sentinel_rel = _SENTINELS[cli_name][0]
    sentinel_path = fake_home / sentinel_rel
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_content: dict = {
        "mcpServers": {
            "hosttilth": {
                "command": "/bin/true",
                "args": [],
            }
        }
    }
    sentinel_path.write_text(json.dumps(sentinel_content, indent=2))
    return sentinel_path


def _make_isolation_spec(cli_name: str) -> IsolationSpec:
    """Return the real IsolationSpec for the given CLI — loaded from the runner YAML."""
    from copeca.config.loader import load_runner

    cfg = load_runner(cli_name)
    return cfg.isolation


def _make_task(repo_name: str) -> Task:
    """Minimal comprehension task — enough to drive run_single."""
    return Task(
        name=f"iso9_{repo_name}",
        source="test",
        repo=repo_name,
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="locate something",
        ground_truth=ComprehensionGroundTruth(required_strings=[]),
    )


def _make_tiny_repo(tmp_path: Path, name: str) -> Path:
    """Create a tiny, committed, branch-initialised git repo."""
    repo_dir = tmp_path / name
    repo_dir.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    return repo_dir


class _StubRepoMgr:
    """Repo manager that uses a pre-built tiny git repo as the worktree."""

    def __init__(self, worktree: Path) -> None:
        self._wt = worktree

    def verify_toolchain(self, key: str) -> None:
        pass

    def create_worktree(
        self,
        repo: str,
        commit: object = None,
        uri: object = None,
        worktree_id: object = None,
    ) -> Path:
        return self._wt

    def setup(self, wt: Path) -> None:
        pass

    def reset(self, wt: Path) -> None:
        pass

    def remove_worktree(self, wt: Path) -> None:
        pass


# ── Core assertion helper ──────────────────────────────────────────────────────


def _run_clean_room_probe(
    cli_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    """Run the clean-room probe for one CLI and return the parsed JSON the stub emitted.

    Steps:
      1. Create fake host home with sentinel.
      2. Patch HOST HOME to fake_host_home (simulate contaminated developer machine).
      3. Patch the required API key env var so provision_arm's preflight passes.
      4. Build a SubprocessRunner whose cli points at the stub (absolute path → passes
         check_tool_availability without PATH manipulation).
      5. Drive it through run_single; parse result_text as JSON.
    """
    # 1. Fake host home with planted sentinel
    fake_host_home = tmp_path / "fake_host_home"
    fake_host_home.mkdir()
    sentinel_path = _make_sentinel(fake_host_home, cli_name)

    # Non-vacuous proof: the sentinel MUST exist in the fake home
    assert sentinel_path.exists(), (
        f"Sentinel {sentinel_path} must exist in fake_host_home before the run "
        "so that broken isolation would expose it to the agent (discrimination check)"
    )

    # 2. Simulate contaminated developer machine — HOST HOME points at fake_host_home
    monkeypatch.setenv("HOME", str(fake_host_home))

    # 3. Patch the API key so provision_arm uses the API-KEY profile (private HOME)
    #    which is required for the clean-room proof: the host sentinel must be hidden
    #    behind a private HOME. Without the key the SUBSCRIPTION profile leaves HOME
    #    unchanged, which would expose the sentinel and fail assertion 2.
    iso = _make_isolation_spec(cli_name)
    if iso.api_key_env:
        monkeypatch.setenv(iso.api_key_env, "test-key-for-iso9")

    # 4. Build the stub agent binary
    stub = _make_stub_agent(tmp_path / f"bin_{cli_name}", cli_name)

    # 5. Build SubprocessRunner with the real isolation descriptor and stub as the cli.
    #    parser=None → run() returns RunResult(result_text=stdout) — raw JSON from stub.
    runner = SubprocessRunner(
        name=cli_name,
        cli=str(stub),  # absolute path; shutil.which(abs_path) returns it when it exists
        default_args=[],
        arg_map={"prompt_separator": ""},
        isolation=iso,
        parser=None,
    )

    # Tiny git repo as the worktree (avoids any ambient files in the tree)
    repo_dir = _make_tiny_repo(tmp_path / f"repo_{cli_name}", f"repo-{cli_name}")
    repo_mgr = _StubRepoMgr(repo_dir)
    task = _make_task(f"repo-{cli_name}")

    # 6. Drive through run_single — mode=None → clean baseline, no integration paths
    record = run_single(
        task=task,
        mode_name="baseline",
        model="test-model",
        runner=runner,
        repo_mgr=repo_mgr,
        repo_uri=str(repo_dir),
        repo_commit=None,
    )

    result_text = record.get("result_text") or ""
    # The stub may append its JSON after the prompt text (some runners include the
    # prompt as an arg); find the last JSON object in the output.
    # The stub always prints one JSON object and exits, so stdout IS that object.
    # result_text may have leading/trailing whitespace; strip and parse.
    probe: dict = json.loads(result_text.strip())
    return probe


# ── Test class — one method per CLI ───────────────────────────────────────────


class TestCleanRoomBaselineIsolation:
    """ISO-9: Prove that a BASELINE run cannot see a planted host MCP config sentinel.

    Each test: plants the sentinel, runs the baseline probe, asserts zero leakage.
    """

    def test_claude_clean_room(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLAUDE: HOME + CLAUDE_CONFIG_DIR redirect hides ~/.claude.json from the agent.

        Assertions:
          1. saw_host_sentinel == False  — agent could NOT reach ~/.claude.json via ~.
          2. home != fake_host_home       — HOME was redirected to a private temp dir.
          3. "--strict-mcp-config" in argv — ISO-2 strict-MCP flag injected (§13.4).
        """
        probe = _run_clean_room_probe("claude", tmp_path, monkeypatch)

        fake_host_home = str(tmp_path / "fake_host_home")

        # Core proof: sentinel not visible (would be True if HOME weren't redirected)
        assert probe["saw_host_sentinel"] is False, (
            f"claude baseline SAW the host sentinel in ~/\n"
            f"  probe HOME: {probe['home']}\n"
            f"  fake_host_home: {fake_host_home}\n"
            "  → Lock 1 (bring-your-own-home) is BROKEN for claude"
        )

        # HOME was redirected away from the fake host home
        assert probe["home"] != fake_host_home, (
            f"claude baseline HOME was NOT redirected away from fake_host_home: {fake_host_home}\n"
            "  → provision_arm did not set HOME to a private temp dir"
        )
        assert probe["home"], "claude baseline HOME must be a non-empty path"

        # strict-MCP flag injected (ISO-2)
        assert "--strict-mcp-config" in probe["argv"], (
            f"claude baseline argv did not contain --strict-mcp-config\n"
            f"  got argv: {probe['argv']}\n"
            "  → ISO-2 strict_mcp_flags not appended by build_command (§13.4)"
        )

    def test_codex_clean_room(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CODEX: HOME + CODEX_HOME redirect hides ~/.codex/config.toml from the agent.

        Assertions:
          1. saw_host_sentinel == False  — agent could NOT reach ~/.codex/config.toml via ~.
          2. home != fake_host_home       — HOME was redirected to a private temp dir.
          3. "--ignore-user-config" in argv — ISO-2 strict-MCP flag injected (§13.4).
        """
        probe = _run_clean_room_probe("codex", tmp_path, monkeypatch)

        fake_host_home = str(tmp_path / "fake_host_home")

        # Core proof: sentinel not visible
        assert probe["saw_host_sentinel"] is False, (
            f"codex baseline SAW the host sentinel in ~/\n"
            f"  probe HOME: {probe['home']}\n"
            f"  fake_host_home: {fake_host_home}\n"
            "  → Lock 1 (bring-your-own-home) is BROKEN for codex"
        )

        # HOME was redirected away from the fake host home
        assert probe["home"] != fake_host_home, (
            f"codex baseline HOME was NOT redirected away from fake_host_home: {fake_host_home}\n"
            "  → provision_arm did not set HOME to a private temp dir"
        )
        assert probe["home"], "codex baseline HOME must be a non-empty path"

        # strict-MCP flag injected (ISO-2, translated as --ignore-user-config for codex)
        assert "--ignore-user-config" in probe["argv"], (
            f"codex baseline argv did not contain --ignore-user-config\n"
            f"  got argv: {probe['argv']}\n"
            "  → ISO-2 strict_mcp_flags not appended by build_command (§13.4)"
        )

    def test_gemini_clean_room(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """GEMINI: HOME + GEMINI_CLI_HOME redirect hides ~/.gemini/settings.json.

        Gemini's strict_mcp_flags is intentionally empty (see gemini.yaml comment):
        isolation relies solely on a FRESH, EMPTY GEMINI_CLI_HOME. A settings.json
        with mcpServers in the fresh home would need to be written there to load MCP;
        none is written → zero MCP servers.

        Assertions:
          1. saw_host_sentinel == False   — agent could NOT reach ~/.gemini/settings.json.
          2. home != fake_host_home        — HOME was redirected to a private temp dir.
          3. config_home_var != fake_home  — GEMINI_CLI_HOME points at the fresh private
                                            home (a different path from fake_host_home),
                                            so no mcpServers from the host are loaded.
        """
        probe = _run_clean_room_probe("gemini", tmp_path, monkeypatch)

        fake_host_home = str(tmp_path / "fake_host_home")

        # Core proof: sentinel not visible
        assert probe["saw_host_sentinel"] is False, (
            f"gemini baseline SAW the host sentinel in ~/\n"
            f"  probe HOME: {probe['home']}\n"
            f"  fake_host_home: {fake_host_home}\n"
            "  → Lock 1 (bring-your-own-home) is BROKEN for gemini"
        )

        # HOME was redirected away from the fake host home
        assert probe["home"] != fake_host_home, (
            f"gemini baseline HOME was NOT redirected away from fake_host_home: {fake_host_home}\n"
            "  → provision_arm did not set HOME to a private temp dir"
        )
        assert probe["home"], "gemini baseline HOME must be a non-empty path"

        # GEMINI_CLI_HOME was set to the fresh private home (not fake_host_home)
        # This is the mechanism that gives zero-MCP isolation for gemini (no settings.json
        # with mcpServers exists in a freshly-created empty directory).
        assert probe["config_home_var"] != fake_host_home, (
            f"gemini baseline GEMINI_CLI_HOME was NOT redirected away from fake_host_home\n"
            f"  GEMINI_CLI_HOME = {probe['config_home_var']!r}\n"
            f"  fake_host_home  = {fake_host_home!r}\n"
            "  → provision_arm did not set GEMINI_CLI_HOME to the private temp dir"
        )
        assert probe["config_home_var"], (
            "gemini baseline GEMINI_CLI_HOME must be set to a non-empty path"
        )
