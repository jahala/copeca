"""Run comparison — pairwise comparison of two JSONL result sets.

Architecture: domain. Pure computation. No I/O, no imports from
runners/repos/results/orchestration.
"""

from typing import Any

from copeca.analysis.stats import cost_per_correct


def _fmt_cpc(cpc: float | None) -> str:
    """Format a cost-per-correct value for display."""
    return f"${cpc:.4f}" if cpc is not None else "n/a (0 correct)"


def compare_runs(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    """Compare two JSONL result sets, produce markdown with per-task deltas.

    Flags tasks where cost-per-correct changed by more than 10%.

    Args:
        before: List of records from the baseline / before run.
        after: List of records from the experimental / after run.

    Returns:
        Markdown string with comparison report.
    """
    if not before and not after:
        return "# Run Comparison\n\n*No results in either run.*\n"

    lines: list[str] = []
    lines.append("# Run Comparison")
    lines.append("")

    # Gather all task names from both sets
    before_tasks: set[str] = {r["task"] for r in before}
    after_tasks: set[str] = {r["task"] for r in after}
    all_tasks = sorted(before_tasks | after_tasks)

    only_before = before_tasks - after_tasks
    only_after = after_tasks - before_tasks

    # ── Overhead per-task table ────────────────────────────────────────────
    lines.append("## Per-Task Deltas")
    lines.append("")
    lines.append("| Task | Before CPC | After CPC | Delta% |")
    lines.append("|------|-----------:|----------:|-------:|")

    flags: list[tuple[str, float]] = []

    for task in all_tasks:
        before_task = [r for r in before if r["task"] == task]
        after_task = [r for r in after if r["task"] == task]

        cpc_before: float | None = cost_per_correct(before_task) if before_task else None
        cpc_after: float | None = cost_per_correct(after_task) if after_task else None

        if before_task and after_task:
            if cpc_before is None or cpc_after is None:
                # At least one side has 0 correct — delta is undefined
                lines.append(f"| {task} | {_fmt_cpc(cpc_before)} | {_fmt_cpc(cpc_after)} | N/A |")
            else:
                if cpc_before > 0:
                    delta_pct = ((cpc_after - cpc_before) / cpc_before) * 100
                elif cpc_after > 0:
                    delta_pct = float("inf")
                else:
                    delta_pct = 0.0

                flag = ""
                if abs(delta_pct) > 10:
                    flags.append((task, delta_pct))
                    flag = " **>10%**"

                lines.append(
                    f"| {task} | {_fmt_cpc(cpc_before)} | {_fmt_cpc(cpc_after)} "
                    f"| {delta_pct:+.1f}%{flag} |"
                )

        elif before_task and not after_task:
            lines.append(f"| {task} | {_fmt_cpc(cpc_before)} | *missing* | N/A |")

        elif not before_task and after_task:
            lines.append(f"| {task} | *missing* | {_fmt_cpc(cpc_after)} | N/A |")

    lines.append("")

    # ── Overall stats ──────────────────────────────────────────────────────
    cpc_all_before: float | None = cost_per_correct(before) if before else None
    cpc_all_after: float | None = cost_per_correct(after) if after else None
    lines.append("## Overall")
    lines.append("")
    lines.append(f"- **Before:** {len(before)} records across {len(before_tasks)} tasks")
    lines.append(f"- **After:** {len(after)} records across {len(after_tasks)} tasks")
    lines.append(f"- **Overall CPC before:** {_fmt_cpc(cpc_all_before)}")
    lines.append(f"- **Overall CPC after:** {_fmt_cpc(cpc_all_after)}")

    if cpc_all_before is not None and cpc_all_after is not None and cpc_all_before > 0:
        overall_delta = ((cpc_all_after - cpc_all_before) / cpc_all_before) * 100
        lines.append(f"- **Overall delta:** {overall_delta:+.1f}%")
    lines.append("")

    # ── Flagged large changes ──────────────────────────────────────────────
    if flags:
        lines.append("## Flagged Tasks (>10% Change)")
        lines.append("")
        for task, delta in flags:
            direction = "decrease" if delta < 0 else "increase"
            lines.append(f"- **{task}:** {delta:+.1f}% {direction}")

        lines.append("")

    # ── Missing tasks ──────────────────────────────────────────────────────
    if only_before or only_after:
        lines.append("## Task Coverage Changes")
        lines.append("")
        if only_before:
            tasks_str = ", ".join(sorted(only_before))
            lines.append(f"- **Removed:** {tasks_str}")
        if only_after:
            tasks_str = ", ".join(sorted(only_after))
            lines.append(f"- **Added:** {tasks_str}")
        lines.append("")

    return "\n".join(lines)
