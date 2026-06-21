"""Markdown report generation from JSONL records.

Architecture: domain. Pure text generation — no I/O, no imports from
runners/repos/results/orchestration.
"""

from typing import Any

from copeca.analysis.stats import (
    ascii_sparkline,
    bootstrap_ci,
    cost_per_correct,
    group_by,
)

_ADVERSARIAL_FLAG_NAMES = [
    "token_snowball",
    "talkative_failure",
    "error",
    "timeout",
    "budget_exhausted",
]


def _compute_per_task_deltas(
    records: list[dict[str, Any]], modes: list[str]
) -> list[float]:
    """Compute per-task cost-per-correct deltas between two modes.

    For each task, compute cost_per_correct for mode[0] and mode[1],
    then return the list of (mode[1] - mode[0]) deltas for tasks where
    both modes have a valid cost.

    Returns empty list if fewer than 2 modes or no shared tasks.
    """
    if len(modes) < 2:
        return []

    m0, m1 = modes[0], modes[1]
    by_task = group_by(records, key="task")

    deltas: list[float] = []
    for task_records in by_task.values():
        by_mode = group_by(task_records, key="mode")
        mode0_recs = by_mode.get(m0, [])
        mode1_recs = by_mode.get(m1, [])
        if not mode0_recs or not mode1_recs:
            continue
        cpc0 = cost_per_correct(mode0_recs)
        cpc1 = cost_per_correct(mode1_recs)
        # Exclude tasks where either mode has no correct answers (undefined CPC)
        if cpc0 is None or cpc1 is None:
            continue
        if cpc0 > 0:
            deltas.append(((cpc1 - cpc0) / cpc0) * 100)

    return deltas


def _has_flags(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries adversarial_flags."""
    for r in records:
        if "adversarial_flags" in r and r["adversarial_flags"] is not None:
            return True
    return False


def _has_turn_data(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries per-turn token data."""
    for r in records:
        if r.get("per_turn_output_tokens") or r.get("per_turn_context_tokens"):
            return True
    return False


def _has_tools(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries a non-empty tool_sequence."""
    return any(
        r.get("tool_sequence") and len(r["tool_sequence"]) > 0
        for r in records
    )


def _has_language(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries a language field."""
    return any(r.get("language") is not None for r in records)


def _has_difficulty(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries a difficulty field."""
    return any(r.get("difficulty") is not None for r in records)


def _has_category(records: list[dict[str, Any]]) -> bool:
    """Check if any record carries a category (capability) field."""
    return any(r.get("category") is not None for r in records)


def _tool_adoption_section(
    records: list[dict[str, Any]],
    by_mode: dict[Any, list[dict[str, Any]]],
    modes: list[str],
) -> list[str]:
    """Build the Tool Adoption section lines.

    Counts records with non-empty tool_sequence vs empty, per mode.
    Returns empty list if no records carry tool_sequence.
    """
    if not _has_tools(records):
        return []

    lines: list[str] = []
    lines.append("### Tool Adoption")
    lines.append("")
    lines.append("| Mode | Runs With Tools | Total Runs | Adoption % |")
    lines.append("|------|----------------:|-----------:|----------:|")

    for mode in modes:
        mode_records = by_mode[mode]
        total = len(mode_records)
        with_tools = sum(
            1 for r in mode_records
            if r.get("tool_sequence") and len(r["tool_sequence"]) > 0
        )
        pct = (with_tools / total * 100) if total > 0 else 0.0
        lines.append(f"| {mode} | {with_tools} | {total} | {pct:.1f}% |")

    lines.append("")
    return lines


def _per_category_section(
    records: list[dict[str, Any]],
    by_mode: dict[Any, list[dict[str, Any]]],
    modes: list[str],
    category: str,
    title: str,
) -> list[str]:
    """Build a per-category cost-per-correct breakdown section.

    Groups records by category field, then computes cost_per_correct
    per category per mode. Returns empty list if the category field
    is not present in any record.

    Args:
        records: All records.
        by_mode: Records grouped by mode (precomputed).
        modes: Sorted list of mode keys.
        category: The field name to group by (e.g., 'language', 'difficulty').
        title: Section heading (e.g., 'Per-Language Breakdown').
    """
    has_category = {
        "language": _has_language,
        "difficulty": _has_difficulty,
        "category": _has_category,
    }.get(category)
    if has_category is None or not has_category(records):
        return []

    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")

    header = f"| {category.capitalize()} |"
    sep = "|------|"
    for mode in modes:
        header += f" {mode} CPC |"
        sep += "------:|"
    if len(modes) == 2:
        header += " Delta% |"
        sep += "-------:|"
    lines.append(header)
    lines.append(sep)

    cat_values = sorted(
        {r.get(category) for r in records if r.get(category) is not None},
        key=lambda v: str(v),
    )

    for cat_val in cat_values:
        cat_records = [r for r in records if r.get(category) == cat_val]
        by_mode_cat = group_by(cat_records, key="mode")
        row = f"| {cat_val} |"
        cpcs: list[float | None] = []
        for mode in modes:
            cpc = cost_per_correct(by_mode_cat.get(mode, []))
            cpcs.append(cpc)
            cpc_cell = f"${cpc:.4f}" if cpc is not None else "n/a (0 correct)"
            row += f" {cpc_cell} |"
        # Delta% (2 modes): the per-capability payoff — where the tool helps.
        if len(modes) == 2:
            c0, c1 = cpcs
            if c0 is not None and c1 is not None and c0 > 0:
                row += f" {((c1 - c0) / c0) * 100:+.1f}% |"
            else:
                row += " N/A |"
        lines.append(row)

    lines.append("")
    return lines


def generate_report(records: list[dict[str, Any]]) -> str:
    """Generate a markdown report from JSONL records.

    Report structure:
    1. Delta-headline: cost-per-correct for each mode + delta + CI
    2. Per-task table: task name | mode1 cost | mode2 cost | delta% [95% CI]
    3. Cost breakdown: input/output/cache tokens per mode
    4. Corrections summary: correct/total per mode
    5. Adversarial Flags summary (if records carry flags)
    6. Token Usage Sparklines (if records carry per-turn data)
    7. Tool Adoption (if records carry tool_sequence)
    8. Per-Language Breakdown (if records carry language)
    9. Per-Difficulty Breakdown (if records carry difficulty)

    Args:
        records: List of dicts (JSONL records) with fields:
            task, mode, total_cost_usd, correct, input_tokens,
            output_tokens, cache_creation_tokens, cache_read_tokens.
            Optional: adversarial_flags, per_turn_output_tokens,
            per_turn_context_tokens, tool_sequence, language, difficulty.

    Returns:
        Markdown string.
    """
    if not records:
        return "## Copeca Report\n\n*No results.*\n"

    # Separate crashed/failed runs (error set) from valid measurements: they are
    # surfaced in a Failed Runs section below but excluded from every metric so a
    # crash can't deflate accuracy or skew cost (shakedown SD-B).
    failed_records = [r for r in records if r.get("error")]
    records = [r for r in records if not r.get("error")]
    if not records:
        return "## Copeca Report\n\n*No valid results — all runs failed.*\n"

    lines: list[str] = []
    lines.append("## Copeca Report")
    lines.append("")
    if failed_records:
        lines.append("### Failed Runs")
        lines.append("")
        lines.append(
            f"{len(failed_records)} run(s) failed and are excluded from the "
            "metrics below."
        )
        for r in failed_records:
            raw = r.get("error") or "unknown error"
            err = str(raw).splitlines()[0][:120]
            lines.append(
                f"- **{r.get('mode', '?')}** / {r.get('task', '?')}: {err}"
            )
        lines.append("")

    # Discover modes
    by_mode = group_by(records, key="mode")
    modes = sorted(by_mode.keys(), key=lambda m: str(m) if m is not None else "")

    # ── 1. Delta-headline: cost-per-correct for each mode + delta + CI ─────
    lines.append("### Cost Per Correct Answer")
    lines.append("")
    lines.append("| Mode | Cost per Correct | Accuracy |")
    lines.append("|------|----------------:|---------:|")

    cpc_by_mode: dict[str, float | None] = {}
    correct_by_mode: dict[str, tuple[int, int]] = {}
    for mode in modes:
        mode_records = by_mode[mode]
        cpc = cost_per_correct(mode_records)
        correct_count = sum(1 for r in mode_records if r.get("correct"))
        total_count = len(mode_records)
        cpc_by_mode[mode] = cpc
        correct_by_mode[mode] = (correct_count, total_count)
        accuracy = f"{correct_count}/{total_count}"
        cpc_cell = f"${cpc:.4f}" if cpc is not None else "n/a (0 correct)"
        lines.append(f"| {mode} | {cpc_cell} | {accuracy} |")

    lines.append("")

    # Delta only when multiple modes exist
    per_task_deltas: list[float] = []
    if len(modes) == 2:
        m0, m1 = modes[0], modes[1]
        cpc0 = cpc_by_mode[m0]
        cpc1 = cpc_by_mode[m1]

        # Compute bootstrap CI on per-task deltas (excludes tasks where either CPC is None)
        per_task_deltas = _compute_per_task_deltas(records, modes)

        if cpc1 is None:
            # Experimental got 0 correct — delta is undefined, not a bargain
            n_correct, n_total = correct_by_mode[m1]
            lines.append(
                f"**Delta:** n/a — {m1} got {n_correct}/{n_total} correct"
            )
        elif cpc0 is None:
            # Baseline got 0 correct — experimental is strictly better, but no ratio
            n_correct, n_total = correct_by_mode[m0]
            lines.append(
                f"**Delta:** n/a — {m0} (baseline) got {n_correct}/{n_total} correct"
            )
        else:
            if cpc0 > 0:
                delta_pct = ((cpc1 - cpc0) / cpc0) * 100
            elif cpc1 > 0:
                delta_pct = float("inf")
            else:
                delta_pct = 0.0
            direction = "lower" if delta_pct < 0 else "higher"

            if per_task_deltas:
                ci_lo, ci_hi, _, _ = bootstrap_ci(per_task_deltas)
                lines.append(
                    f"**Delta:** {m1} is {delta_pct:+.1f}% {direction} than {m0} "
                    f"(${cpc1:.4f} vs ${cpc0:.4f}) "
                    f"[95% CI: {ci_lo:+.1f}%, {ci_hi:+.1f}%]"
                )
            else:
                lines.append(
                    f"**Delta:** {m1} is {delta_pct:+.1f}% {direction} than {m0} "
                    f"(${cpc1:.4f} vs ${cpc0:.4f})"
                )
        lines.append("")

    # ── 2. Per-task table ──────────────────────────────────────────────────
    by_task = group_by(records, key="task")
    tasks = sorted(by_task.keys(), key=lambda t: str(t) if t is not None else "")

    lines.append("### Per-Task Cost")
    lines.append("")

    header = "| Task |"
    sep = "|------|"
    for mode in modes:
        header += f" {mode} |"
        sep += "------:|"
    if len(modes) == 2:
        if per_task_deltas:
            header += " Delta% [95% CI] |"
            sep += "------------------:|"
        else:
            header += " Delta% |"
            sep += "-------:|"
    lines.append(header)
    lines.append(sep)

    for task in tasks:
        task_records = by_task[task]
        by_mode_in_task = group_by(task_records, key="mode")

        row = f"| {task} |"
        costs: list[float | None] = []
        for mode in modes:
            mode_recs = by_mode_in_task.get(mode, [])
            cpc = cost_per_correct(mode_recs)
            costs.append(cpc)
            cpc_cell = f"${cpc:.4f}" if cpc is not None else "n/a (0 correct)"
            row += f" {cpc_cell} |"

        if len(modes) == 2:
            c0, c1 = costs
            if c0 is None or c1 is None:
                row += " N/A |"
            elif c0 > 0:
                delta = ((c1 - c0) / c0) * 100
                row += f" {delta:+.1f}% |"
            else:
                row += " N/A |"

        lines.append(row)

    lines.append("")

    # ── 3. Cost breakdown: tokens per mode ─────────────────────────────────
    lines.append("### Token Breakdown")
    lines.append("")
    lines.append("| Mode | Total Input | Total Output | Total Cache Create | Total Cache Read |")
    lines.append("|------|------------:|-------------:|-------------------:|-----------------:|")

    for mode in modes:
        mode_records = by_mode[mode]
        total_input = sum(r.get("input_tokens", 0) or 0 for r in mode_records)
        total_output = sum(r.get("output_tokens", 0) or 0 for r in mode_records)
        total_cache_create = sum(r.get("cache_creation_tokens", 0) or 0 for r in mode_records)
        total_cache_read = sum(r.get("cache_read_tokens", 0) or 0 for r in mode_records)

        lines.append(
            f"| {mode} | {total_input:,} | {total_output:,} | "
            f"{total_cache_create:,} | {total_cache_read:,} |"
        )

    lines.append("")

    # ── 4. Corrections summary: correct/total per mode ─────────────────────
    lines.append("### Corrections Summary")
    lines.append("")
    lines.append("| Mode | Correct | Total | Rate |")
    lines.append("|------|--------:|------:|-----:|")

    for mode in modes:
        mode_records = by_mode[mode]
        correct_count = sum(1 for r in mode_records if r.get("correct"))
        total_count = len(mode_records)
        rate = (correct_count / total_count * 100) if total_count > 0 else 0.0
        lines.append(f"| {mode} | {correct_count} | {total_count} | {rate:.1f}% |")

    lines.append("")

    # ── 5. Adversarial Flags (if records carry flags) ──────────────────────
    if _has_flags(records):
        lines.append("### Adversarial Flags")
        lines.append("")
        lines.append("| Flag | Rate |")
        lines.append("|------|-----:|")

        all_flags: list[dict[str, Any]] = []
        for r in records:
            flags = r.get("adversarial_flags")
            if flags is not None and isinstance(flags, dict):
                all_flags.append(flags)

        total_with_flags = len(all_flags)
        for flag_name in _ADVERSARIAL_FLAG_NAMES:
            true_count = sum(
                1 for f in all_flags
                if f.get(flag_name) is True
            )
            rate_pct = (true_count / total_with_flags * 100) if total_with_flags > 0 else 0.0
            lines.append(f"| {flag_name} | {rate_pct:.1f}% |")

        lines.append("")

    # ── 6. Token Usage Sparklines (if records carry per-turn data) ─────────
    if _has_turn_data(records):
        lines.append("### Token Usage Sparklines")
        lines.append("")
        lines.append("*Per-turn output token sequences, sampled at 20 points.*")
        lines.append("")

        for task in tasks:
            task_records = by_task[task]
            by_m = group_by(task_records, key="mode")
            for mode in modes:
                for rec in by_m.get(mode, []):
                    spark_values = rec.get("per_turn_output_tokens")
                    if not spark_values or len(spark_values) < 2:
                        continue
                    spark = ascii_sparkline(spark_values, width=20)
                    mn = min(spark_values)
                    mx = max(spark_values)
                    lines.append(
                        f"- **{task}** ({mode}): `{spark}` "
                        f"min={mn} max={mx} n={len(spark_values)} turns"
                    )

        lines.append("")

    # ── 7. Tool Adoption (if records carry tool_sequence) ──────────────────
    lines.extend(_tool_adoption_section(records, by_mode, modes))

    # ── 8. Per-Language Breakdown (if records carry language) ───────────────
    lines.extend(
        _per_category_section(
            records, by_mode, modes, "language", "Per-Language Breakdown"
        )
    )

    # ── 9. Per-Difficulty Breakdown (if records carry difficulty) ───────────
    lines.extend(
        _per_category_section(
            records, by_mode, modes, "difficulty", "Per-Difficulty Breakdown"
        )
    )

    # ── 10. Per-Capability Breakdown (if records carry category) ────────────
    # The payoff: cost-per-correct sliced by what the task demands (locate/trace/
    # fix/debug), so the delta reveals WHERE a tool helps, not just how much overall.
    lines.extend(
        _per_category_section(
            records, by_mode, modes, "category", "Per-Capability Breakdown"
        )
    )

    return "\n".join(lines)
