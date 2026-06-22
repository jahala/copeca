"""Per-arm harness provisioning for copeca benchmark modes.

Architecture: orchestration layer. Coordinates domain types with adapter
operations. Filesystem and subprocess I/O is at the edge — `provision_arm`
is the single boundary function; the dataclass is pure state.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from copeca.config.models import IsolationSpec, Mode


@dataclass
class ArmHarness:
    """Isolated harness for one benchmark arm (baseline or experimental)."""

    env: dict[str, str] = field(default_factory=dict)
    config_dir: Path | None = None
    wrapper: list[str] | None = None
    mcp_config_path: str | None = None
    # Path to the per-run private HOME directory (outside the worktree).
    # The caller must remove this directory in the same finally block that
    # removes the worktree so no host footprint remains (architecture §13.2).
    private_home: str | None = None


def provision_arm(
    mode: Mode | None,
    worktree: Path,
    arm_name: str = "arm",
    isolation: IsolationSpec | None = None,
) -> ArmHarness:
    """Provision an isolated harness for a benchmark mode arm.

    Every arm — baseline INCLUDED — receives:
    * A fresh, empty private HOME (a temp dir outside the worktree) so the
      agent never reads/writes the host's ~/.claude.json, ~/.codex/, etc.
    * The isolation.config_home_env var set to that HOME (when declared).
    * isolation.disable_ambient_env and isolation.disable_telemetry_env
      merged into the arm env.

    For arms that declare integration paths (mcp_config, env, agent_config,
    wrapper, setup) the usual per-arm config dir is also created.

    Args:
        mode: Mode model with integration paths, or None for a clean baseline
              (no integration paths, only isolation env vars are applied).
        worktree: Worktree directory for this arm.
        arm_name: Label for this arm ("baseline" or "experimental").
        isolation: Per-CLI clean-room descriptor (architecture §13.4).
                   When None an empty IsolationSpec is used (safe defaults).

    Returns:
        ArmHarness with env, config_dir, wrapper, and private_home.

    Raises:
        RuntimeError: If isolation.requires_api_key_env names a var absent
                      from the host environment, or if a setup command fails.
    """
    iso = isolation if isolation is not None else IsolationSpec()

    # ── API-key preflight ─────────────────────────────────────────────
    # Fail loudly BEFORE creating any filesystem state if the required API
    # key is absent — auth is via API key, never the host login session
    # (architecture §13.2).
    if iso.requires_api_key_env and iso.requires_api_key_env not in os.environ:
        raise RuntimeError(
            f"Required API key env var '{iso.requires_api_key_env}' is not set. "
            f"Export it before running copeca (e.g. export {iso.requires_api_key_env}=<key>)."
        )

    # ── Integration paths (absent for clean baseline / mode=None) ────
    has_paths = bool(
        mode is not None
        and (mode.mcp_config or mode.env or mode.agent_config or mode.wrapper or mode.setup)
    )

    config_dir: Path | None = None
    mcp_config_path: str | None = None
    wrapper: list[str] | None = None

    if has_paths and mode is not None:
        # ── Per-arm directory ─────────────────────────────────────────
        arms_dir = worktree / ".copeca-arms" / arm_name
        arms_dir.mkdir(parents=True, exist_ok=True)

        # ── agent_config: copy settings → per-arm config dir ─────────
        if mode.agent_config is not None:
            config_dir = arms_dir / "config"
            config_dir.mkdir(exist_ok=True)
            src = Path(mode.agent_config)
            _copy_settings_file(src, config_dir)

        # ── mcp_config: write dict as JSON → arms_dir/mcp.json ───────
        if mode.mcp_config is not None:
            mcp_file = arms_dir / "mcp.json"
            with open(mcp_file, "w", encoding="utf-8") as fh:
                json.dump(mode.mcp_config, fh, indent=2)
            mcp_config_path = str(mcp_file)

        # ── wrapper: return as-is (caller prefixes command) ──────────
        wrapper = list(mode.wrapper) if mode.wrapper else None

        # ── setup: run commands in worktree ───────────────────────────
        if mode.setup:
            _run_setup_commands(mode.setup, worktree)

    # ── Private HOME (outside the worktree) ───────────────────────────
    # Created AFTER the fallible integration-path work above (agent_config
    # copy, setup commands) so a failure there never leaks an orphaned temp
    # dir — run_single's finally only removes a home it gets on the harness.
    # mkdtemp produces a directory owned and removable by copeca; placing it
    # outside the worktree keeps it from showing up as an untracked file.
    private_home_path = tempfile.mkdtemp(prefix="copeca-home-")

    # ── Build arm env — isolation vars + mode.env (mode wins) ────────
    # Order of precedence (highest last, as dict.update wins):
    #   1. HOME → private_home_path (always)
    #   2. config_home_env → private_home_path (when declared in descriptor)
    #   3. disable_ambient_env keys
    #   4. disable_telemetry_env keys
    #   5. mode.env keys (the integration-specific overrides win last)
    env: dict[str, str] = {"HOME": private_home_path}
    if iso.config_home_env:
        env[iso.config_home_env] = private_home_path
    env.update(iso.disable_ambient_env)
    env.update(iso.disable_telemetry_env)
    if mode is not None and mode.env:
        env.update(mode.env)

    return ArmHarness(
        env=env,
        config_dir=config_dir,
        wrapper=wrapper,
        mcp_config_path=mcp_config_path,
        private_home=private_home_path,
    )


# ── I/O helpers (private, at the edge) ────────────────────────────────────────


def _copy_settings_file(src: Path, dest_dir: Path) -> None:
    """Copy a settings JSON file into *dest_dir*, keeping its basename."""
    if not src.exists():
        raise FileNotFoundError(f"agent_config file not found: {src}")
    # Parse + re-serialize so we only copy valid JSON (defensive).
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)
    dest = dest_dir / src.name
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _run_setup_commands(commands: list[str], cwd: Path) -> None:
    """Run each setup command in *cwd*. Raises RuntimeError on failure.

    Commands are split into argv form via ``shlex.split`` and executed with
    ``shell=False`` — no shell features (globbing, pipes, ``&&``, ``;``) are
    available.  If a shell is genuinely needed, pass an explicit argv such as
    ``["bash", "-c", "cmd1 && cmd2"]``.
    """
    for cmd in commands:
        result = subprocess.run(
            shlex.split(cmd),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Setup command '{cmd}' failed with exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
