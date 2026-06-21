"""Single-run orchestrator — the atomic unit of copeca measurement.

Architecture: orchestration layer. Coordinates domain + adapters.
Depends on port interfaces (BaseRunner), never on concrete adapters.
The orchestrator returns a record dict; the CLI caller persists it.
"""

import importlib.metadata
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copeca.config.models import AdversarialThresholds, EditGroundTruth, Mode, Scenario, Task
from copeca.orchestration.state import provision_arm
from copeca.runners.base import BaseRunner
from copeca.runners.cost import compute_cost
from copeca.tasks.mutations import apply_mutations
from copeca.tasks.validator import check_correctness

logger = logging.getLogger(__name__)


def run_single(
    task: Task,
    mode_name: str,
    model: str,
    runner: BaseRunner,
    repo_mgr: Any,
    repo_uri: str | None = None,
    repo_commit: str | None = None,
    pricing: dict[str, float] | None = None,
    artifacts: bool = False,
    timeout_seconds: int = 300,
    mode: Mode | None = None,
    worktree_id: str | None = None,
    budget_usd: float | None = None,
    adversarial_thresholds: AdversarialThresholds | None = None,
) -> dict[str, Any]:
    """Execute a single copeca run — the complete measurement pipeline.

    Args:
        task: The task to run.
        mode_name: Mode identifier (baseline, experimental tool).
        model: Full model ID from runner pricing keys.
        runner: The BaseRunner instance (subprocess, future HTTP, etc.).
        repo_mgr: Repo manager providing worktree operations.
        repo_uri: Git clone URL (only needed on first clone for this repo).
        repo_commit: Git ref to pin the worktree at (None = HEAD).
        pricing: Per-million-token pricing dict with keys input, cache_creation,
                 cache_read, output. When provided, total_cost_usd is computed from
                 tokens * rates; the parser's cost is stored as vendor_cost_usd.
                 When None, total_cost_usd falls back to the parser's cost.
        artifacts: Whether to produce a .copeca zip.
        timeout_seconds: Wall-clock timeout for this run's subprocess.
        mode: The Mode model for this arm. When provided, provision_arm applies
              env overrides and config-dir isolation. None = clean baseline.
        worktree_id: Per-work-item discriminator forwarded to repo_mgr so
              concurrent workers for the same repo get distinct worktree paths.
              None lets repo_mgr generate a UUID (safe but non-deterministic).
        budget_usd: Dollar cap for this run; sourced from scenario.budget_usd.
              When provided, passed to build_command for runner enforcement and
              used to compute budget_exhausted.  None = no cap.
        adversarial_thresholds: Per-scenario flag thresholds. When None, the
              AdversarialThresholds defaults apply.

    Returns:
        The JSONL record as a dict. The caller is responsible for persisting it.
    """
    # 1. Verify toolchain
    repo_mgr.verify_toolchain(task.repo)

    # 2. Create worktree at pinned commit — scoped to this work item so
    #    concurrent workers for the same repo never share a path.
    worktree = repo_mgr.create_worktree(
        task.repo, commit=repo_commit, uri=repo_uri, worktree_id=worktree_id
    )

    try:
        # 3. Run setup
        repo_mgr.setup(worktree)

        # 3.5. Provision arm harness — applies mode.env, config_dir, wrapper.
        # Baseline (mode=None) → harness.env is empty → child gets allowlist only.
        # Experimental mode → harness.env carries mode.env merged on top.
        if mode is not None:
            harness = provision_arm(mode, worktree=Path(worktree), arm_name=mode_name)
        else:
            from copeca.orchestration.state import ArmHarness
            harness = ArmHarness()

        # 4. Apply mutations (edit tasks only) — run inside worktree
        if task.mutations:
            apply_mutations(task.mutations, base_path=Path(worktree))

        # 5. Build command (apply wrapper prefix if harness declares one) and run.
        command = runner.build_command(
            model=model,
            prompt=task.prompt,
            budget=budget_usd,
            mcp_config=harness.mcp_config_path,
        )
        if harness.wrapper:
            command = list(harness.wrapper) + command
        # Build run env: start from mode.env overrides, then inject config dir if
        # the runner declares a config_dir_env name (runner-config-driven, not hardcoded).
        run_env = dict(harness.env or {})
        if harness.config_dir and getattr(runner, "config_dir_env", None):
            run_env[runner.config_dir_env] = str(harness.config_dir)
        parsed = runner.run(command, cwd=str(worktree), env=run_env or None)

        # 5.5. Run test_command for edit tasks (P0 bug fix)
        test_command_passed: bool | None = None
        test_command_record: dict[str, Any] | None = None
        if isinstance(task.ground_truth, EditGroundTruth) and task.ground_truth.test_command:
            try:
                tc_result = subprocess.run(
                    task.ground_truth.test_command,
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                test_command_passed = (tc_result.returncode == 0)
                test_command_record = {
                    "command": task.ground_truth.test_command,
                    "passed": test_command_passed,
                    "stdout": tc_result.stdout[:2000] if tc_result.stdout else "",
                    "stderr": tc_result.stderr[:2000] if tc_result.stderr else "",
                }
            except subprocess.TimeoutExpired:
                test_command_passed = False
                test_command_record = {
                    "command": task.ground_truth.test_command,
                    "passed": False,
                    "stdout": "",
                    "stderr": "test command timed out",
                }
            except Exception:
                test_command_passed = False
                test_command_record = {
                    "command": task.ground_truth.test_command,
                    "passed": False,
                    "stdout": "",
                    "stderr": "test command execution failed",
                }
        correct, detail = check_correctness(
            task.ground_truth,
            parsed.result_text,
            test_command_passed=test_command_passed,
        )

        # 6.5. Compute cost from tokens * pricing (when pricing is provided)
        _divergence: float | None = None
        _divergence_warning: str | None = None
        if pricing is not None:
            computed_cost = compute_cost(
                tokens={
                    "input_tokens": parsed.total_input_tokens,
                    "output_tokens": parsed.total_output_tokens,
                    "cache_creation_tokens": parsed.total_cache_creation_tokens,
                    "cache_read_tokens": parsed.total_cache_read_tokens,
                },
                pricing=pricing,
            )
            total_cost_usd = computed_cost
            vendor_cost_usd = parsed.total_cost_usd
            # Check for vendor cost divergence (>5% triggers warning)
            if vendor_cost_usd is not None and vendor_cost_usd > 0:
                divergence = abs(computed_cost - vendor_cost_usd) / vendor_cost_usd
                if divergence > 0.05:
                    _divergence = divergence
                    _divergence_warning = (
                        f"Computed cost ({computed_cost:.4f}) differs from "
                        f"vendor cost ({vendor_cost_usd:.4f}) by {divergence*100:.1f}%"
                    )
        else:
            total_cost_usd = parsed.total_cost_usd
            vendor_cost_usd = None
        # 6.6 Compute adversarial flags — must run after grading so correct/
        #     result_text are available.
        _thresholds = adversarial_thresholds or AdversarialThresholds()
        flags = _compute_adversarial_flags(
            parsed=parsed,
            total_cost_usd=total_cost_usd,
            budget_usd=budget_usd,
            timeout_seconds=timeout_seconds,
            correct=correct,
            thresholds=_thresholds,
        )

        # 7. Build JSONL record
        record: dict[str, Any] = {
            "task": task.name,
            "repo": task.repo,
            "mode": mode_name,
            "model": model,
            "runner": runner.name,
            "repetition": 0,
            "timestamp": datetime.now(UTC).isoformat(),
            "correct": correct,
            "correctness_detail": {
                "required_strings_passed": detail.required_strings_passed,
                "all_of_passed": detail.all_of_passed,
                "forbidden_strings_passed": detail.forbidden_strings_passed,
                "test_command_passed": detail.test_command_passed,
            },
            "num_turns": parsed.num_turns,
            "num_tool_calls": parsed.num_tool_calls,
            "total_cost_usd": total_cost_usd,
            "duration_ms": parsed.duration_ms,
            "context_tokens": (
                parsed.total_input_tokens + parsed.total_cache_creation_tokens
            ),
            "output_tokens": parsed.total_output_tokens,
            "input_tokens": parsed.total_input_tokens,
            "cache_creation_tokens": parsed.total_cache_creation_tokens,
            "cache_read_tokens": parsed.total_cache_read_tokens,
            "result_text": parsed.result_text[:5000] if parsed.result_text else "",
            "tool_sequence": [tc.name for tc in parsed.tool_calls],
            "error": parsed.error,
            "adversarial_flags": flags,
            "test_command_output": test_command_record,
            "metadata": {
                "copeca_version": importlib.metadata.version("copeca"),
                "task_version": task.version,
            },
        }

        if vendor_cost_usd is not None:
            record["vendor_cost_usd"] = vendor_cost_usd

        if _divergence is not None:
            record["metadata"]["vendor_cost_divergence"] = _divergence
            record["metadata"]["vendor_cost_divergence_warning"] = _divergence_warning

        return record


    finally:
        # 9. Reset worktree
        repo_mgr.reset(worktree)


def _compute_adversarial_flags(
    parsed: Any,
    total_cost_usd: float,
    budget_usd: float | None,
    timeout_seconds: int,
    correct: bool | None,
    thresholds: AdversarialThresholds,
) -> dict[str, bool | None]:
    """Compute adversarial flags from parsed run data (plan §5).

    Flags that cannot be computed from available data are None (not False).
    All thresholds come from the caller-supplied AdversarialThresholds.
    """
    # talkative_failure: verbose output AND wrong answer.
    # null when correctness is unknown (correct=None) — data genuinely missing.
    if correct is None:
        talkative_failure: bool | None = None
    else:
        output_tokens = parsed.total_output_tokens
        talkative_failure = (
            output_tokens > thresholds.talkative_tokens and not correct
        )

    # tool_storm: excessive tool calls.
    # null only if num_tool_calls is unavailable; the RunResult always has it,
    # so this will always be bool in practice.
    num_calls = parsed.num_tool_calls
    tool_storm: bool | None = num_calls > thresholds.tool_storm_calls

    # budget_exhausted: cost >= cap AND no result produced.
    if budget_usd is None:
        budget_exhausted: bool | None = None
    else:
        result_empty = not parsed.result_text  # covers "" and None
        budget_exhausted = total_cost_usd >= budget_usd and result_empty

    return {
        "timeout": (
            parsed.duration_ms >= timeout_seconds * 1000
            if timeout_seconds > 0
            else None
        ),
        "budget_exhausted": budget_exhausted,
        "error": parsed.error is not None,
        "token_snowball": _check_token_snowball(parsed, thresholds.snowball_factor),
        "talkative_failure": talkative_failure,
        "tool_storm": tool_storm,
    }


def _check_token_snowball(parsed: Any, factor: float = 2.0) -> bool | None:
    """Check if any turn's output grows past num_turns × avg(first_3) × factor.

    Plan §5 formula: max(per_turn) > num_turns × avg(first_3_turns) × factor
    Returns None when data is genuinely missing (< 3 turns or zero avg).
    """
    if parsed.num_turns < 3 or not parsed.turns:
        return None
    first_three = parsed.turns[:3]
    avg_first = sum(t.output_tokens for t in first_three) / len(first_three)
    if avg_first == 0:
        return None
    threshold = parsed.num_turns * avg_first * factor
    max_output = max(t.output_tokens for t in parsed.turns)
    return max_output > threshold


def run_matrix(
    scenario: Scenario,
    tasks: list[Task],
    modes: list[str],
    runner_factory: Any,
    repo_mgr: Any,
    repos: dict[str, Any] | None = None,
    results_path: Path | None = None,
    max_workers: int = 1,
    pricing: dict[str, dict[str, float]] | None = None,
    mode_defs: dict[str, Mode] | None = None,
) -> list[dict[str, Any]]:
    """Run a scenario matrix: tasks x modes x reps x models concurrently.

    Builds the full cartesian product work list, then dispatches each
    work item to a ThreadPoolExecutor. Each worker creates its own runner
    and worktree, coarsening external processes while I/O waits.

    Args:
        scenario: The scenario defining the matrix shape.
        tasks: Pre-loaded Task instances matching scenario.tasks.
        modes: List of mode names to run for each task.
        runner_factory: Callable(mode, model) -> BaseRunner.
        repo_mgr: Repo manager providing worktree operations.
        repos: Dict mapping repo keys to Repo models (for URIs and commits).
        results_path: Path to the JSONL output file.
        max_workers: Maximum concurrent workers (default 1 = sequential).
        mode_defs: Dict mapping mode names to Mode models. Each work item's
                   mode_obj is resolved from here so provision_arm applies the
                   mode's env/wrapper/setup. When None (or a name is absent),
                   that arm runs the clean baseline harness.

    Returns:
        List of JSONL record dicts, one per run.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    task_lookup = {t.name: t for t in tasks}
    repos_dict = repos or {}

    # Build the full work list: (task, mode, model, rep, repo_uri, repo_commit)
    work_items: list[dict[str, Any]] = []
    for task_name in scenario.tasks:
        task = task_lookup.get(task_name)
        if task is None:
            logger.warning(
                "Skipping task '%s' — not found in loaded tasks", task_name
            )
            continue

        repo_info = repos_dict.get(task.repo)
        repo_uri = repo_info.url if repo_info else None
        repo_commit = repo_info.commit if repo_info else None

        for mode_name in modes:
            for rep in range(scenario.repetitions):
                for model in scenario.models:
                    work_items.append({
                        "task": task,
                        "task_name": task_name,
                        "mode_name": mode_name,
                        "model": model,
                        "rep": rep,
                        "repo_uri": repo_uri,
                        "repo_commit": repo_commit,
                        "mode_obj": (mode_defs or {}).get(mode_name),
                    })

    logger.info(
        "Matrix: %d work items, max_workers=%d",
        len(work_items), max_workers,
    )

    records: list[dict[str, Any]] = []

    if not work_items:
        return records

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {
            executor.submit(_run_one_work_item, item, runner_factory, repo_mgr,
                            scenario, pricing): item
            for item in work_items
        }

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                record = future.result()
                records.append(record)
            except Exception as exc:
                logger.error(
                    "Run failed: task=%s mode=%s model=%s rep=%d: %s",
                    item["task_name"], item["mode_name"],
                    item["model"], item["rep"], exc,
                )
                error_record: dict[str, Any] = {
                    "task": item["task"].name,
                    "repo": item["task"].repo,
                    "mode": item["mode_name"],
                    "model": item["model"],
                    "runner": "unknown",
                    "repetition": item["rep"],
                    "timestamp": datetime.now(UTC).isoformat(),
                    "correct": False,
                    "error": str(exc),
                }
                records.append(error_record)

    return records


def _run_one_work_item(
    item: dict[str, Any],
    runner_factory: Any,
    repo_mgr: Any,
    scenario: Scenario,
    pricing: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    """Execute a single work item in a thread worker.

    Creates its own runner instance and delegates to run_single.
    This is the callable submitted to the thread pool.
    """
    runner = runner_factory(item["mode_name"], item["model"])
    model_pricing: dict[str, float] | None = None
    if pricing is not None:
        model_pricing = pricing.get(item["model"])

    logger.info(
        "Running: task=%s mode=%s model=%s rep=%d",
        item["task_name"], item["mode_name"], item["model"], item["rep"],
    )

    mode_obj: Mode | None = item.get("mode_obj")
    # Derive a stable, human-readable discriminator from the work-item tuple.
    # This is embedded in the worktree directory name so concurrent workers
    # for the same repo always land on distinct filesystem paths.
    task_key = item["task_name"].replace("/", "_")
    mode_key = item["mode_name"].replace("/", "_")
    model_key = item["model"].replace("/", "_")
    worktree_id = f"{task_key}__{mode_key}__{model_key}__rep{item['rep']}"
    record = run_single(
        task=item["task"],
        mode_name=item["mode_name"],
        model=item["model"],
        runner=runner,
        repo_mgr=repo_mgr,
        repo_uri=item["repo_uri"],
        repo_commit=item["repo_commit"],
        pricing=model_pricing,
        timeout_seconds=scenario.timeout_seconds,
        mode=mode_obj,
        worktree_id=worktree_id,
        budget_usd=scenario.budget_usd,
        adversarial_thresholds=scenario.adversarial_thresholds,
    )
    record["repetition"] = item["rep"]
    return record
