"""Orchestration validation — compatibility checks and staleness warnings.

Architecture: orchestration layer. Pure functions — no I/O, no subprocess.
All data is passed in; warnings are returned as strings.
"""

import shutil
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from copeca.config.models import Scenario


def _today() -> date:
    """Return today's date. Isolated for testability via mock.patch."""
    return date.today()


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
