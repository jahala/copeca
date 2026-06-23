"""Orchestration validation — compatibility checks, staleness warnings, and version
provenance helpers (ISO-8).

Architecture: orchestration layer. Most functions are pure (no I/O). The ISO-8
version-resolution helpers (resolve_tool_version, resolve_cli_version,
detect_multi_version_installs) are the I/O edge: they run subprocesses and scan
PATH dirs. They are best-effort: any failure returns None / empty list and logs a
warning — they NEVER raise or crash a run.
"""

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from copeca.config.models import IsolationSpec, Scenario

logger = logging.getLogger(__name__)

# Timeout for version-probe subprocesses (seconds). Short: this is a preflight,
# not a long-running task. If the binary is unresponsive, we just record None.
_VERSION_TIMEOUT = 5


def _today() -> date:
    """Return today's date. Isolated for testability via mock.patch."""
    return date.today()


# ── ISO-8: Version provenance helpers (I/O edge) ──────────────────────────────


def resolve_tool_version(command: str) -> tuple[str | None, str | None]:
    """Resolve the version + absolute path of the tool-under-test binary.

    Runs ``<command> --version``, captures the first line of stdout.  The
    absolute path is resolved via ``shutil.which`` (or the command itself if
    it is already absolute).

    Best-effort: any failure (binary missing, flag unsupported, timeout)
    returns ``(None, None)`` and logs a warning. NEVER raises.

    Args:
        command: The binary name or absolute path (from mcp_config command).

    Returns:
        ``(version_string, absolute_path)`` — both None on any failure.
    """
    # Resolve absolute path first (may be a bare name like "tilth")
    resolved = shutil.which(command) or (command if Path(command).is_absolute() else None)
    if resolved is None or not Path(resolved).is_file():
        logger.warning("ISO-8: cannot resolve tool binary %r — tool_version will be None", command)
        return None, None

    try:
        result = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning(
                "ISO-8: %r --version exited %d — tool_version will be None",
                resolved,
                result.returncode,
            )
            return None, resolved

        first_line = (result.stdout or "").splitlines()[0].strip() if result.stdout else None
        if not first_line:
            logger.warning(
                "ISO-8: %r --version produced empty output — tool_version will be None", resolved
            )
            return None, resolved

        return first_line, resolved

    except subprocess.TimeoutExpired:
        logger.warning("ISO-8: %r --version timed out — tool_version will be None", resolved)
        return None, resolved
    except Exception as exc:
        logger.warning(
            "ISO-8: unexpected error running %r --version: %s — tool_version will be None",
            resolved,
            exc,
        )
        return None, resolved


def resolve_cli_version(isolation: IsolationSpec | None) -> str | None:
    """Resolve the runner CLI version via isolation.version_cmd.

    Runs the first entry of ``isolation.version_cmd`` as a subprocess and
    returns the first line of stdout.  Returns ``None`` when the spec is
    absent, version_cmd is empty, or any error occurs.

    Best-effort: NEVER raises.

    Args:
        isolation: The runner's IsolationSpec (or None).

    Returns:
        Version string (first stdout line, stripped) or None.
    """
    if isolation is None or not isolation.version_cmd:
        return None

    cmd = list(isolation.version_cmd)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning(
                "ISO-8: version_cmd %r exited %d — cli_version will be None", cmd, result.returncode
            )
            return None

        first_line = (result.stdout or "").splitlines()[0].strip() if result.stdout else None
        if not first_line:
            logger.warning(
                "ISO-8: version_cmd %r produced empty output — cli_version will be None", cmd
            )
            return None

        return first_line

    except subprocess.TimeoutExpired:
        logger.warning("ISO-8: version_cmd %r timed out — cli_version will be None", cmd)
        return None
    except Exception as exc:
        logger.warning(
            "ISO-8: unexpected error running version_cmd %r: %s — cli_version will be None",
            cmd,
            exc,
        )
        return None


def detect_multi_version_installs(
    configured_command: str,
    binary_name: str,
    path_dirs: list[str] | None = None,
) -> list[tuple[str, str | None]]:
    """Scan PATH dirs for copies of *binary_name* alongside the configured one.

    Returns a list of ``(absolute_path, version_or_None)`` tuples — one per
    distinct path found (configured copy + any PATH copies).  When more than
    one entry is returned, a ``logging.warning`` is emitted naming each path
    and version and which is the configured one.

    This is a WARNING-only helper: the return value is informational; the
    caller never aborts based on it.

    Args:
        configured_command: The command string from the mode's mcp_config
                            (may be absolute or a bare binary name).
        binary_name: The basename to scan for across PATH dirs (e.g. "tilth").
        path_dirs: Explicit list of directories to scan.  When None, uses
                   ``os.environ.get("PATH", "").split(os.pathsep)``.

    Returns:
        List of ``(absolute_path, version)`` — may include None versions for
        unreachable binaries.  Empty when the configured binary doesn't exist
        and nothing is on PATH.
    """
    if path_dirs is None:
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)

    seen_paths: set[str] = set()
    findings: list[tuple[str, str | None]] = []

    # 1. Resolve the configured command first
    configured_abs = shutil.which(configured_command) or (
        configured_command if Path(configured_command).is_absolute() else None
    )
    if configured_abs and Path(configured_abs).is_file():
        version, _ = resolve_tool_version(configured_abs)
        findings.append((configured_abs, version))
        seen_paths.add(configured_abs)

    # 2. Scan PATH dirs for the basename
    for dir_str in path_dirs:
        candidate = Path(dir_str) / binary_name
        if not candidate.is_file():
            continue
        candidate_abs = str(candidate.resolve())
        if candidate_abs in seen_paths:
            continue
        seen_paths.add(candidate_abs)
        version, _ = resolve_tool_version(candidate_abs)
        findings.append((candidate_abs, version))

    # 3. Emit a warning if multiple installations found
    if len(findings) > 1:
        detail = "; ".join(
            f"{p!r} ({v or 'version unknown'})" + (" [configured]" if p == configured_abs else "")
            for p, v in findings
        )
        logger.warning(
            "ISO-8 multi-version: multiple %r installations detected — "
            "ensure the configured path is the intended version. Found: %s",
            binary_name,
            detail,
        )

    return findings


# ── Staleness, compat, availability (pre-existing pure functions) ──────────────


def check_pricing_staleness(pricing: dict[str, Any]) -> list[str]:
    """Check pricing entries for staleness (>30 days since updated).

    For each model entry with an 'updated' field, compare against
    today's date. Emit a warning string for each stale entry.

    Args:
        pricing: Dict mapping model names to their pricing dicts.
                 Each pricing dict should have an 'updated' field
                 with an ISO date string (YYYY-MM-DD).

    Returns:
        List of warning strings, one per stale model entry.
        Empty list if all pricing is current.
    """
    warnings: list[str] = []
    today = _today()
    threshold = timedelta(days=30)

    for model_name, entry in pricing.items():
        if not isinstance(entry, dict):
            continue

        updated_str = entry.get("updated")
        if updated_str is None:
            warnings.append(f"Pricing for '{model_name}' is missing 'updated' field")
            continue

        try:
            updated = date.fromisoformat(updated_str)
        except (ValueError, TypeError):
            warnings.append(
                f"Pricing for '{model_name}' has unparseable 'updated' date: {updated_str!r}"
            )
            continue

        age = today - updated
        if age > threshold:
            warnings.append(
                f"Pricing for '{model_name}' is {age.days} days old (updated {updated_str})"
            )

    return warnings


def check_mode_runner_compat(mode: Any, runner: Any) -> list[str]:
    """Check mode<->runner compatibility, returning advisory warnings.

    Args:
        mode: Mode model with integration paths (mcp_config, env,
              agent_config, wrapper, tools).
        runner: BaseRunner with arg_map and invoke_template.

    Returns:
        List of warning strings. Empty if fully compatible.
        Warnings are advisory — never block execution.
    """
    warnings: list[str] = []

    # 1. mcp_config check
    if mode.mcp_config is not None:
        has_mcp_arg = "mcp_config" in runner.arg_map
        has_mcp_template = "{mcp_config}" in runner.invoke_template
        if not has_mcp_arg and not has_mcp_template:
            warnings.append(
                f"Mode '{mode.name}' uses mcp_config but runner "
                f"'{runner.name}' has no mcp_config support"
            )

    # 2. agent_config check
    if mode.agent_config is not None:
        warnings.append(
            f"Mode '{mode.name}' uses agent_config — ensure the runner "
            f"supports --agent-config-dir or equivalent"
        )

    # 3. wrapper check
    if mode.wrapper is not None:
        warnings.append(
            f"Mode '{mode.name}' uses wrapper — compatibility depends on "
            f"the runner CLI accepting command prefix"
        )

    # 4. env check
    if mode.env is not None:
        # claude runner is known to support env natively.
        # Known env-support runners can be extended here.
        env_support_runners: set[str] = {"claude"}
        if runner.name not in env_support_runners:
            warnings.append(
                f"Mode '{mode.name}' uses env but runner '{runner.name}' "
                f"may not propagate environment variables"
            )

    return warnings


def check_tool_availability(
    mode: Any,
    runner_cli: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Pre-run check that a mode's declared tools are actually launchable.

    A mode can declare a tool the host doesn't have installed (an MCP server
    command, a wrapper command). If the agent launches anyway, the tool silently
    fails to attach and the experimental arm runs as a tool-less baseline — a
    FALSE NULL. Run this BEFORE spending so the caller can abort instead of
    paying for an invalid comparison.

    `which` is injected (defaults to shutil.which) so the logic stays a pure
    function over its inputs and is testable without touching the real PATH.

    Args:
        mode: The Mode model for this arm (or None for a clean baseline).
        runner_cli: The runner's CLI binary name to verify on PATH.
        which: PATH-resolver returning a path or None. Injected for testing.

    Returns:
        List of error strings (empty = everything declared is launchable). A
        non-empty list means the experimental arm cannot run as declared.
    """
    errors: list[str] = []

    if runner_cli and which(runner_cli) is None:
        errors.append(f"runner CLI '{runner_cli}' not found on PATH")

    if mode is None:
        return errors

    mcp = mode.mcp_config or {}
    servers = mcp.get("mcpServers", {}) if isinstance(mcp, dict) else {}
    for name, spec in servers.items():
        cmd = spec.get("command") if isinstance(spec, dict) else None
        if cmd and which(cmd) is None:
            errors.append(
                f"mode '{mode.name}': MCP server '{name}' command '{cmd}' not found on PATH"
            )

    if mode.wrapper and which(mode.wrapper[0]) is None:
        errors.append(f"mode '{mode.name}': wrapper command '{mode.wrapper[0]}' not found on PATH")

    return errors


def scan_worktree_for_ambient_files(
    worktree: Path,
    ambient_files: list[str],
) -> list[str]:
    """Scan the worktree tree for ambient instruction files.

    Walks the entire worktree recursively and returns the relative paths of any
    files whose basenames appear in ambient_files. A non-empty return means the
    worktree is contaminated and the run must be refused (Lock 2a, §13.3).

    Pure: takes a path + names, returns findings; no raising, no global state.

    Args:
        worktree: Root directory of the checked-out repo clone.
        ambient_files: File basenames to match (e.g. [CLAUDE.md, AGENTS.md]).

    Returns:
        List of relative path strings (relative to worktree) for every match.
        Empty list = clean worktree.
    """
    if not ambient_files:
        return []

    target_names = set(ambient_files)
    findings: list[str] = []
    for path in worktree.rglob("*"):
        if path.is_file() and path.name in target_names:
            findings.append(str(path.relative_to(worktree)))
    return findings


def validate_scenario(
    scenario: Scenario,
    available_tasks: set[str],
    available_modes: set[str],
) -> list[str]:
    """Pre-flight scenario validation. Returns list of error/warning strings.

    Empty list = scenario is valid. Non-empty = at least one issue was found.
    The caller decides whether to stop (on errors) or continue (on warnings).

    Checks:
    - All tasks in scenario.tasks exist in available_tasks
    - All modes in scenario.modes exist in available_modes
    - At least 1 repetition (enforced by Pydantic, cross-check here)
    - budget > 0 (enforced by Pydantic, cross-check here)
    - Fewer than 5 reps produces an advisory warning

    Args:
        scenario: The scenario to validate.
        available_tasks: Set of task names available to load.
        available_modes: Set of mode names available to use.

    Returns:
        List of issue strings. Empty if the scenario passes all checks.
    """
    issues: list[str] = []

    # 1. Task existence
    for task_name in scenario.tasks:
        if task_name not in available_tasks:
            issues.append(f"Task '{task_name}' not found in available tasks")

    # 2. Mode existence
    for mode_name in scenario.modes:
        if mode_name not in available_modes:
            issues.append(f"Mode '{mode_name}' not found in available modes")

    # 3. Budget (Pydantic enforces ge=0.0, but budget=0 is nonsensical)
    if scenario.budget_usd <= 0:
        issues.append(f"Budget must be greater than 0 (got {scenario.budget_usd})")

    # 4. Low repetitions — advisory warning
    if scenario.repetitions < 5:
        issues.append(
            f"Only {scenario.repetitions} repetition(s) configured. "
            f"For statistical significance, 5+ repetitions are recommended."
        )

    return issues
