"""Per-arm harness provisioning for copeca benchmark modes.

Architecture: orchestration layer. Coordinates domain types with adapter
operations. Filesystem and subprocess I/O is at the edge — `provision_arm`
is the single boundary function; the dataclass is pure state.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from copeca.config.models import Mode


@dataclass
class ArmHarness:
    """Isolated harness for one benchmark arm (baseline or experimental)."""

    env: dict[str, str] = field(default_factory=dict)
    config_dir: Path | None = None
    wrapper: list[str] | None = None


def provision_arm(mode: Mode, worktree: Path, arm_name: str = "arm") -> ArmHarness:
    """Provision an isolated harness for a benchmark mode arm.

    Creates a per-arm config directory under ``<worktree>/.copeca-arms/<arm_name>/``,
    copies the agent_config settings file (when declared), records env overrides,
    records the wrapper prefix, and runs setup commands (when declared).

    Baseline mode (no integration paths) produces a clean harness:
    empty env, no config_dir, no wrapper, no setup.

    Args:
        mode: Mode model with integration paths.
        worktree: Worktree directory for this arm.
        arm_name: Label for this arm ("baseline" or "experimental").

    Returns:
        ArmHarness with env, config_dir, and wrapper.

    Raises:
        RuntimeError: If a setup command exits non-zero.
    """
    # ── Baseline: no integration paths → clean harness ───────────────
    has_paths = bool(
        mode.mcp_config
        or mode.env
        or mode.agent_config
        or mode.wrapper
        or mode.setup
    )
    if not has_paths:
        return ArmHarness()

    # ── Per-arm directory ────────────────────────────────────────────
    arms_dir = worktree / ".copeca-arms" / arm_name
    arms_dir.mkdir(parents=True, exist_ok=True)

    # ── agent_config: copy settings → per-arm config dir ─────────────
    config_dir: Path | None = None
    if mode.agent_config is not None:
        config_dir = arms_dir / "config"
        config_dir.mkdir(exist_ok=True)
        src = Path(mode.agent_config)
        _copy_settings_file(src, config_dir)

    # ── env: return as-is (caller applies during subprocess) ─────────
    env: dict[str, str] = dict(mode.env) if mode.env else {}

    # ── wrapper: return as-is (caller prefixes command) ──────────────
    wrapper: list[str] | None = list(mode.wrapper) if mode.wrapper else None

    # ── setup: run commands in worktree ──────────────────────────────
    if mode.setup:
        _run_setup_commands(mode.setup, worktree)

    return ArmHarness(env=env, config_dir=config_dir, wrapper=wrapper)


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
    """Run each setup command in *cwd*. Raises RuntimeError on failure."""
    for cmd in commands:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Setup command '{cmd}' failed with exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
