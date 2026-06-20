"""copeca CLI — typer app with validate, list, run, analyze, verify, init."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from copeca.config.loader import (
    LoadError,
    SchemaValidationError,
    load_tasks_from_dir,
)
from copeca.config.models import Repo
from copeca.results.writer import append_jsonl
from copeca.runners.parsers.stream_json import StreamJsonParser


# ── Cost-safeguard helpers (pure logic + thin I/O) ─────────────────────────


def extract_vendor_divergence_warning(record: dict[str, Any]) -> str | None:
    """Return the vendor cost divergence warning string from a record, or None.

    The warning is stored in record["metadata"]["vendor_cost_divergence_warning"]
    only when divergence exceeds the 5% threshold (see orchestration/run.py).

    Pure function — no I/O.
    """
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    return metadata.get("vendor_cost_divergence_warning")


def emit_vendor_divergence_warning(warning: str | None) -> None:
    """Echo a vendor cost divergence warning to stderr, if present."""
    if warning is not None:
        typer.echo(f"Warning: {warning}", err=True)


def emit_staleness_warnings(warnings: list[str]) -> None:
    """Echo each pricing staleness warning to stderr."""
    for w in warnings:
        typer.echo(f"Warning: {w}", err=True)

app = typer.Typer(
    name="copeca",
    help="cost per correct answer — a neutral, reproducible, verifiable benchmark for CLI-based coding agents",
    no_args_is_help=True,
)


@app.command()
def validate(
    tasks_dir: Path = typer.Argument(..., help="Directory containing task YAML files"),
    repos_path: Path = typer.Option(
        None,
        "--repos",
        help="Path to repos.yaml for cross-document repo reference validation",
    ),
    strict: bool = typer.Option(False, "--strict", help="Also fail on warnings"),
) -> None:
    """Validate task YAML files against the JSON Schema and repo registry."""
    # Layer 3 autodiscovery: if --repos not given, check repos.yaml in cwd
    if repos_path is None:
        cwd_repos = Path("repos.yaml")
        if cwd_repos.exists():
            repos_path = cwd_repos

    repos: dict[str, Repo] | None = None
    if repos_path is not None:
        from copeca.config.loader import load_repos

        repos = load_repos(repos_path)

    try:
        tasks = load_tasks_from_dir(tasks_dir, repos=repos)
    except FileNotFoundError:
        typer.echo(f"Error: directory not found: {tasks_dir}", err=True)
        raise typer.Exit(code=2)
    except SchemaValidationError as e:
        typer.echo(f"Validation error: {e}", err=True)
        raise typer.Exit(code=1)
    except LoadError as e:
        typer.echo(f"Error loading tasks: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Validated {len(tasks)} task(s) successfully.")


@app.command(name="list")
def list_tasks(
    tasks_dir: Path = typer.Argument(".", help="Directory containing task YAML files"),
) -> None:
    """List discovered tasks."""
    try:
        tasks = load_tasks_from_dir(tasks_dir)
    except FileNotFoundError:
        typer.echo(f"Error: directory not found: {tasks_dir}", err=True)
        raise typer.Exit(code=2)
    except LoadError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    for t in tasks:
        typer.echo(f"  {t.name:40s} {t.type.value:15s} {t.language.value:8s} {t.difficulty.value}")


@app.command()
def run(
    task: Path = typer.Option(..., "--task", help="Path to task YAML or scenario YAML file"),
    runner: str = typer.Option("claude", "--runner", help="Runner name"),
    model: str = typer.Option("", "--model", help="Model ID (matches pricing key; optional for scenario mode)"),
    mode: str = typer.Option("default", "--mode", help="Mode name (single-task mode only)"),
    budget: float = typer.Option(1.0, "--budget", help="Max spend per run in USD"),
    timeout: int = typer.Option(300, "--timeout", help="Max wall time in seconds"),
    artifacts: bool = typer.Option(False, "--artifacts", help="Produce .copeca zip"),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed output"),
) -> None:
    """Run a task or scenario through a CLI agent and write JSONL results.

    If the file is a scenario (detected by the presence of a 'tasks' list
    or a filename containing 'scenario'), all tasks x modes x reps are run.
    Otherwise, the file is treated as a single task.
    """
    from copeca.config.loader import (
        load_modes,
        load_repos,
        load_scenario,
        load_task,
        load_tasks_from_dir,
    )
    from copeca.orchestration.run import run_matrix, run_single as run_single_task
    from copeca.orchestration.validation import validate_scenario
    from copeca.repos.manager import GitWorktreeManager
    from copeca.runners.subprocess import SubprocessRunner

    import yaml

    # ── Detect: scenario or single task? ────────────────────────────────
    lookup_text = task.read_text()
    doc = yaml.safe_load(lookup_text)
    is_scenario = (
        isinstance(doc, dict)
        and "tasks" in doc
        or "scenario" in task.name.lower()
    )

    repos_path = Path("repos.yaml")
    if not repos_path.exists():
        repos_path = task.parent.parent / "repos.yaml" if task.parent.parent.name else Path("repos.yaml")
    repos = load_repos(repos_path) if repos_path.exists() else {}

    # ── Bug 2: Load pricing from defaults/runners/ YAML ──────────────────
    pricing: dict[str, dict[str, float]] | None = None
    pricing_path = Path("defaults") / "runners" / f"{runner}.yaml"
    if pricing_path.exists():
        with open(pricing_path) as pf:
            runner_doc = yaml.safe_load(pf)
            if isinstance(runner_doc, dict) and "pricing" in runner_doc:
                pricing = runner_doc["pricing"]
                from copeca.orchestration.validation import check_pricing_staleness
                emit_staleness_warnings(check_pricing_staleness(pricing))

    # ── Shared: build a real runner with the stream-json parser ──────────
    # Default Claude Code interface — verify/override per agent
    # (config-dir via CLAUDE_CONFIG_DIR env, MCP via --mcp-config).
    # These are runner-config values, not hardcoded core behavior.
    def build_runner(cli_name: str = runner) -> SubprocessRunner:
        r = SubprocessRunner(
            name=cli_name,
            cli=cli_name,
            timeout=timeout,
            default_args=["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence"],
            arg_map={
                "model": "--model",
                "budget": "--max-budget-usd",
                "system_prompt": "--system-prompt",
                "mcp_config": "--mcp-config",
                "prompt_separator": "--",
            },
            parser=StreamJsonParser(),
            config_dir_env="CLAUDE_CONFIG_DIR",
        )
        return r

    if is_scenario:
        # ── Scenario mode ───────────────────────────────────────────────
        typer.echo(f"Detected scenario file: {task}")
        scenario = load_scenario(task)

        tasks_dir = task.parent.parent / "tasks" if task.parent.parent.name else Path("tasks")
        if not tasks_dir.is_dir():
            tasks_dir = Path("tasks")
        loaded_tasks = load_tasks_from_dir(tasks_dir)
        task_names = {t.name for t in loaded_tasks}

        # Load each mode's YAML into a Mode model so run_matrix can apply its
        # integration paths. An unknown mode (no YAML) fails loudly here.
        modes_dirs = [task.parent.parent / "defaults" / "modes", Path("defaults") / "modes"]
        try:
            mode_defs = load_modes(scenario.modes, modes_dirs=modes_dirs)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        # Tautology fix: validate against the set of modes that actually loaded,
        # not the scenario's own mode list (which would always pass).
        issues = validate_scenario(scenario, task_names, set(mode_defs))
        if issues:
            typer.echo("Scenario validation warnings:", err=True)
            for issue in issues:
                typer.echo(f"  - {issue}", err=True)

        repo_mgr = GitWorktreeManager(repos_dir=Path("repos"))

        results_dir = Path(scenario.output_dir) if scenario.output_dir else Path("results")
        results_path = results_dir / f"{scenario.name}.jsonl"

        total_runs = len(scenario.tasks) * len(scenario.modes) * scenario.repetitions * len(scenario.models)
        typer.echo(
            f"Running scenario '{scenario.name}': "
            f"{len(scenario.tasks)} task(s) x {len(scenario.modes)} mode(s) x "
            f"{scenario.repetitions} rep(s) = {total_runs} total runs"
        )

        records = run_matrix(
            scenario=scenario,
            tasks=loaded_tasks,
            modes=scenario.modes,
            runner_factory=lambda mode_name, model_name: build_runner(runner),
            repo_mgr=repo_mgr,
            repos=repos,
            results_path=results_path,
            max_workers=scenario.max_workers,
            pricing=pricing,
            mode_defs=mode_defs,
        )

        for record in records:
            append_jsonl(record, results_path)
            emit_vendor_divergence_warning(extract_vendor_divergence_warning(record))

        if artifacts:
            for record in records:
                if record.get("correct") and "artifact_path" not in record:
                    from copeca.results.artifact import build_artifact
            typer.echo("Artifact creation in matrix mode: use single-task mode with --artifacts")

        if verbose:
            correct_count = sum(1 for r in records if r.get("correct"))
            typer.echo(f"Results: {correct_count}/{len(records)} correct")
            typer.echo(f"Written to: {results_path}")
    else:
        # ── Single-task mode ────────────────────────────────────────────
        task_obj = load_task(task)

        runner_instance = build_runner(runner)

        repo_mgr = GitWorktreeManager(repos_dir=Path("repos"))
        repo_uri: str | None = None
        repo_commit: str | None = None
        if task_obj.repo in repos:
            repo_uri = repos[task_obj.repo].url
            repo_commit = repos[task_obj.repo].commit

        # Resolve pricing for the chosen model
        model_pricing: dict[str, float] | None = None
        if pricing is not None and model:
            model_pricing = pricing.get(model)

        results_path = Path("results") / "bench.jsonl"
        record = run_single_task(
            task=task_obj,
            mode_name=mode,
            model=model,
            runner=runner_instance,
            repo_mgr=repo_mgr,
            repo_uri=repo_uri,
            repo_commit=repo_commit,
            pricing=model_pricing,
            artifacts=artifacts,
        )

        # I/O at the boundary (architecture.md §2):
        append_jsonl(record, results_path)
        emit_vendor_divergence_warning(extract_vendor_divergence_warning(record))
        if artifacts:
            from copeca.results.artifact import build_artifact
            worktree = repo_mgr.create_worktree(task_obj.repo, commit=repo_commit, uri=repo_uri)
            try:
                artifact_path = build_artifact(record, worktree, Path("results"))
                typer.echo(f"Artifact: {artifact_path}")
            finally:
                repo_mgr.reset(worktree)

        if verbose:
            typer.echo(f"correct: {record['correct']}")
            typer.echo(f"cost: ${record['total_cost_usd']:.4f}")
            typer.echo(f"duration: {record['duration_ms']}ms")



@app.command()
def check_task(
    task_file: Path = typer.Argument(..., help="Path to an edit task YAML file"),
    repos_dir: Path = typer.Option(
        Path("repos"), "--repos-dir", help="Directory for git repos"
    ),
) -> None:
    """Verify an edit task: test passes on clean code, fails after mutation."""
    from copeca.config.loader import load_repos, load_task
    from copeca.orchestration.check import verify_mutation_validity
    from copeca.repos.manager import GitWorktreeManager

    repos_path = Path("repos.yaml")
    if not repos_path.exists():
        repos_path = task_file.parent.parent / "repos.yaml"
    repos = load_repos(repos_path) if repos_path.exists() else {}

    task_obj = load_task(task_file)
    repo_mgr = GitWorktreeManager(repos_dir=repos_dir)

    valid, message = verify_mutation_validity(task_obj, repo_mgr, repos)

    if valid:
        typer.echo(message)
    else:
        typer.echo(f"FAILED: {message}", err=True)
        raise typer.Exit(code=1)


@app.command()
def verify(
    artifact: Path = typer.Argument(
        None, help="Path to a .copeca artifact to verify (omit when using --batch)"
    ),
    batch: Path = typer.Option(
        None, "--batch", help="Directory of .copeca zips to check for completeness"
    ),
    scenario: Path = typer.Option(
        None, "--scenario", help="Scenario YAML to compare against (required with --batch)"
    ),
) -> None:
    """Verify a .copeca artifact's integrity, or check batch completeness.

    Single-artifact mode (default): verifies the content_hash chain of one zip.

    Batch mode (--batch <dir> --scenario <path>): compares the artifacts present
    in <dir> against the full expected set from <scenario> and reports missing
    or unexpected runs.  Exits non-zero when any runs are missing.
    """
    if batch is not None:
        # ── Batch completeness mode ──────────────────────────────────────────
        if scenario is None:
            typer.echo("Error: --scenario is required when using --batch", err=True)
            raise typer.Exit(code=2)

        from copeca.config.loader import load_scenario
        from copeca.results.verification import verify_batch

        try:
            scn = load_scenario(scenario)
        except FileNotFoundError:
            typer.echo(f"Error: scenario not found: {scenario}", err=True)
            raise typer.Exit(code=2)

        result = verify_batch(batch, scenario=scn)

        typer.echo(f"Authentic:  {result['authentic']}")
        if result["tampered"]:
            typer.echo(f"Tampered:   {', '.join(result['tampered'])}", err=True)  # type: ignore[arg-type]

        missing_ids: list[dict[str, Any]] = result["missing_ids"]  # type: ignore[assignment]
        unexpected_ids: list[dict[str, Any]] = result["unexpected_ids"]  # type: ignore[assignment]

        if missing_ids:
            typer.echo(f"Missing ({len(missing_ids)}):", err=True)
            for ident in missing_ids:
                typer.echo(
                    f"  {ident['task']}  mode={ident['mode']}  model={ident['model']}"
                    f"  rep{ident['repetition']:02d}",
                    err=True,
                )

        if unexpected_ids:
            typer.echo(f"Unexpected ({len(unexpected_ids)}):")
            for ident in unexpected_ids:
                typer.echo(
                    f"  {ident['task']}  mode={ident['mode']}  model={ident['model']}"
                    f"  rep{ident['repetition']:02d}"
                )

        if result["missing"] or result["tampered"]:
            raise typer.Exit(code=1)
        return

    # ── Single-artifact mode ─────────────────────────────────────────────────
    if artifact is None:
        typer.echo("Error: provide ARTIFACT or --batch / --scenario", err=True)
        raise typer.Exit(code=2)

    from copeca.results.verification import verify_artifact

    try:
        valid, message = verify_artifact(artifact)
    except FileNotFoundError:
        typer.echo(f"Error: file not found: {artifact}", err=True)
        raise typer.Exit(code=2)

    if valid:
        typer.echo(message)
    else:
        typer.echo(f"FAILED: {message}", err=True)
        raise typer.Exit(code=1)


@app.command()
def analyze(
    results: Path = typer.Argument(..., help="Path to JSONL results file"),
    output: Path = typer.Option(None, "-o", "--output", help="Write report to file"),
    fmt: str = typer.Option("markdown", "--format", help="Output format (markdown or json)"),
) -> None:
    """Analyze benchmark results and produce a report."""
    import json

    from copeca.analysis.stats import bootstrap_ci, compute_stats, cost_per_correct
    from copeca.analysis.report import generate_report

    if not results.exists():
        typer.echo(f"Error: file not found: {results}", err=True)
        raise typer.Exit(code=2)

    with open(results) as f:
        records = []
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        typer.echo("Error: no records found in results file", err=True)
        raise typer.Exit(code=1)

    if fmt == "json":
        report_data = {
            "num_records": len(records),
            "num_correct": sum(1 for r in records if r.get("correct")),
            "cost_per_correct": cost_per_correct(records),
            "total_cost_usd": sum(r.get("total_cost_usd", 0) for r in records),
        }
        out = json.dumps(report_data, indent=2)
    else:
        out = generate_report(records)

    if output:
        output.write_text(out)
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(out)


@app.command()
def init(
    path: str = typer.Argument(".", help="Directory to initialize"),
) -> None:
    """Initialize a new copeca benchmark directory."""
    import shutil

    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).resolve().parents[2]

    package_tasks = project_root / "tasks"
    if package_tasks.is_dir():
        dest_tasks = target / "tasks"
        if not dest_tasks.exists():
            shutil.copytree(package_tasks, dest_tasks)

    package_repos = project_root / "repos.yaml"
    if package_repos.exists():
        shutil.copy2(package_repos, target / "repos.yaml")

    package_defaults = project_root / "defaults"
    if package_defaults.is_dir():
        dest_defaults = target / "defaults"
        if not dest_defaults.exists():
            shutil.copytree(package_defaults, dest_defaults)

    (target / "scenarios").mkdir(exist_ok=True)
    (target / "results").mkdir(exist_ok=True)

    typer.echo(f"Initialized copeca benchmark at {target}")
    typer.echo("  tasks/     — seed corpus tasks")
    typer.echo("  repos.yaml — repository registry")
    typer.echo("  defaults/  — runner pricing and mode configs")
    typer.echo("  scenarios/ — scenario files go here")
    typer.echo("  results/   — benchmark output")


@app.command()
def compare(
    before: Path = typer.Argument(..., help="Path to first JSONL results file"),
    after: Path = typer.Argument(..., help="Path to second JSONL results file"),
) -> None:
    """Compare two JSONL result files and show per-task deltas."""
    import json

    from copeca.analysis.compare import compare_runs

    if not before.exists():
        typer.echo(f"Error: file not found: {before}", err=True)
        raise typer.Exit(code=2)
    if not after.exists():
        typer.echo(f"Error: file not found: {after}", err=True)
        raise typer.Exit(code=2)

    with open(before) as f:
        before_records = [json.loads(line) for line in f if line.strip()]
    with open(after) as f:
        after_records = [json.loads(line) for line in f if line.strip()]

    typer.echo(compare_runs(before_records, after_records))


if __name__ == "__main__":
    app()
