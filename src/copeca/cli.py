"""copeca CLI — typer app with validate, list, run, analyze, verify, init."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from copeca.config.loader import (
    LoadError,
    SchemaValidationError,
    load_runner,
    load_tasks_from_dir,
)
from copeca.config.models import Repo
from copeca.config.resources import data_path
from copeca.results.writer import append_jsonl
from copeca.runners.parsers import get_parser
from copeca.runners.subprocess import SubprocessRunner

# Packaged default blocklist — always present in a wheel install.
# A project-local override (scripts/contamination_blocklist.txt in cwd) takes
# precedence if it exists, matching the same autodiscovery pattern as repos.yaml.
_BLOCKLIST_LOCAL = Path("scripts") / "contamination_blocklist.txt"
_BLOCKLIST_PACKAGED = data_path("contamination_blocklist.txt")


# ── Contamination provenance helpers (pure logic + thin I/O) ──────────────


def _find_blocked_source_tasks(
    tasks: list[Any],
    blocked_sources: set[str],
) -> list[tuple[str, str]]:
    """Return (task_name, reason) pairs for tasks whose source is blocked.

    Pure function — no I/O.

    Args:
        tasks: Loaded Task model objects (must have .name and .source attrs).
        blocked_sources: Set of benchmark names to reject.

    Returns:
        List of (task_name, reason) for every blocked task; empty if clean.
    """
    from copeca.contamination import check_source_provenance

    findings: list[tuple[str, str]] = []
    for task in tasks:
        source = getattr(task, "source", "") or ""
        flagged, reason = check_source_provenance(source, blocked_sources)
        if flagged:
            findings.append((task.name, reason))
    return findings


def _find_tool_coupled_tasks(tasks: list[Any]) -> list[tuple[str, str]]:
    """Return (task_name, reason) for every task whose text prescribes a tool/method.

    Pure function — no I/O. A task must name the information it requires, not how to
    retrieve it (see agnosticism.py), so the A/B stays method-neutral.
    """
    from copeca.agnosticism import check_tool_agnostic

    findings: list[tuple[str, str]] = []
    for task in tasks:
        description = getattr(task, "description", "") or ""
        for reason in check_tool_agnostic(task.name, task.prompt, description):
            findings.append((task.name, reason))
    return findings


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


def build_runner(
    runner_name: str,
    timeout: int,
    runner_dirs: list[Path] | None = None,
) -> SubprocessRunner:
    """Construct a SubprocessRunner from a runner YAML — config-driven.

    The CLI interface (cli, default_args, arg_map, invoke_template,
    config_dir_env) and the output parser come entirely from
    ``<runner_name>.yaml``; no agent's flags are hardcoded here. This is what
    makes copeca genuinely multi-CLI: a new agent is added by writing a YAML,
    not by editing this function.

    Args:
        runner_name: Runner name; resolves ``<dir>/<runner_name>.yaml``.
        timeout: Max wall time in seconds for the subprocess.
        runner_dirs: Directories to search for the runner YAML (defaults to the
            packaged ``defaults/runners`` via load_runner).

    Returns:
        A SubprocessRunner wired with the YAML's interface and parser.

    Raises:
        FileNotFoundError: If no runner YAML resolves for ``runner_name``.
        ParserNotFoundError: If the YAML names a parser that isn't built.
    """
    cfg = load_runner(runner_name, runner_dirs=runner_dirs)
    return SubprocessRunner(
        name=runner_name,
        cli=cfg.cli,
        timeout=timeout,
        default_args=cfg.default_args,
        arg_map=cfg.arg_map,
        invoke_template=cfg.invoke_template,
        prepend_system_prompt=cfg.prepend_system_prompt,
        mcp_via_config_overrides=cfg.mcp_via_config_overrides,
        parser=get_parser(cfg.parser),
        config_dir_env=cfg.config_dir_env,
    )


def _build_artifacts_for_records(
    records: list[dict[str, Any]],
    task_by_name: dict[str, Any],
    repos: dict[str, Repo],
    repo_mgr: Any,
    output_dir: Path,
    signing_key: Any,
    keep_worktrees: bool,
) -> list[Path]:
    """Build (and optionally sign) one .copeca artifact per result record.

    Every record is evidence — correct and incorrect alike — so each gets an
    artifact: cost-per-correct depends on the failures too, and ``verify`` checks
    the full set against the JSONL. Worktrees are re-created once per repo (the
    pinned commit is shared across a repo's records) and reset unless
    ``keep_worktrees``. This is the single artifact path shared by scenario
    (matrix) and single-task mode — I/O lives here at the boundary, never in
    orchestration.

    Args:
        records: Result records to package.
        task_by_name: Map of task name -> Task, used to resolve each record's repo.
        repos: Repo registry (name -> Repo) for url/commit lookup.
        repo_mgr: Worktree manager exposing create_worktree / reset.
        output_dir: Directory where the .copeca zips are written.
        signing_key: Optional Ed25519 private key for a detached signature.
        keep_worktrees: When True, worktrees are left in place for inspection.

    Returns:
        The artifact paths written.
    """
    from copeca.results.artifact import build_artifact

    # Group by repo so each worktree is created once and reused for its records.
    by_repo: dict[str | None, list[dict[str, Any]]] = {}
    for record in records:
        task_obj = task_by_name.get(record.get("task"))
        repo_key = task_obj.repo if task_obj is not None else None
        by_repo.setdefault(repo_key, []).append(record)

    paths: list[Path] = []
    for repo_key, repo_records in by_repo.items():
        repo_info = repos.get(repo_key) if repo_key is not None else None
        repo_uri = repo_info.url if repo_info is not None else None
        repo_commit = repo_info.commit if repo_info is not None else None
        worktree = repo_mgr.create_worktree(repo_key, commit=repo_commit, uri=repo_uri)
        try:
            for record in repo_records:
                paths.append(build_artifact(record, worktree, output_dir, sign_key=signing_key))
        finally:
            if not keep_worktrees:
                repo_mgr.reset(worktree)
    return paths


app = typer.Typer(
    name="copeca",
    help=(
        "cost per correct answer — a neutral, reproducible, verifiable benchmark"
        " for CLI-based coding agents"
    ),
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
        raise typer.Exit(code=2) from None
    except SchemaValidationError as e:
        typer.echo(f"Validation error: {e}", err=True)
        raise typer.Exit(code=1) from e
    except LoadError as e:
        typer.echo(f"Error loading tasks: {e}", err=True)
        raise typer.Exit(code=1) from e

    # ── Provenance / contamination check ────────────────────────────────────
    # Load blocked source benchmarks and flag any task whose `source:` field
    # names a blocked benchmark.  Project-local override takes precedence;
    # falls back to the packaged default (always present in a wheel install).
    blocklist_path = _BLOCKLIST_LOCAL if _BLOCKLIST_LOCAL.exists() else _BLOCKLIST_PACKAGED
    from copeca.contamination import load_blocked_sources

    blocked_sources = load_blocked_sources(blocklist_path)
    blocked_findings = _find_blocked_source_tasks(tasks, blocked_sources)
    if blocked_findings:
        for task_name, reason in blocked_findings:
            typer.echo(
                f"Contamination: task '{task_name}' blocked — {reason}",
                err=True,
            )
        raise typer.Exit(code=1)

    # ── Tool-agnosticism check ──────────────────────────────────────────────
    # A task must name the information it requires, never the retrieval method:
    # tool names / "search for" / single-shot-aggregator cues would bias the A/B
    # (the method is the variable under test). See agnosticism.py.
    coupled_findings = _find_tool_coupled_tasks(tasks)
    if coupled_findings:
        for task_name, reason in coupled_findings:
            typer.echo(
                f"Tool-coupling: task '{task_name}' is not tool-agnostic — {reason}",
                err=True,
            )
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
        raise typer.Exit(code=2) from None
    except LoadError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    for t in tasks:
        typer.echo(f"  {t.name:40s} {t.type.value:15s} {t.language.value:8s} {t.difficulty.value}")


@app.command()
def run(
    task: Path = typer.Option(..., "--task", help="Path to task YAML or scenario YAML file"),
    runner: str = typer.Option("claude", "--runner", help="Runner name"),
    model: str = typer.Option(
        "", "--model", help="Model ID (matches pricing key; optional for scenario mode)"
    ),
    mode: str = typer.Option("default", "--mode", help="Mode name (single-task mode only)"),
    budget: float = typer.Option(1.0, "--budget", help="Max spend per run in USD"),
    timeout: int = typer.Option(300, "--timeout", help="Max wall time in seconds"),
    artifacts: bool = typer.Option(False, "--artifacts", help="Produce .copeca zip"),
    sign_key: Path = typer.Option(
        None,
        "--sign-key",
        help="Ed25519 private key PEM. Signs each .copeca artifact's content_hash "
        "with a detached signature (real tamper-evidence). Requires --artifacts.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed output"),
    keep_worktrees: bool = typer.Option(
        False,
        "--keep-worktrees",
        help="Preserve run worktrees (and per-arm .copeca-arms/) for debugging "
        "instead of resetting them after each run.",
    ),
) -> None:
    """Run a task or scenario through a CLI agent and write JSONL results.

    If the file is a scenario (detected by the presence of a 'tasks' list
    or a filename containing 'scenario'), all tasks x modes x reps are run.
    Otherwise, the file is treated as a single task.
    """
    import yaml

    from copeca.config.loader import (
        load_modes,
        load_repos,
        load_scenario,
        load_task,
        load_tasks_from_dir,
    )
    from copeca.orchestration.run import run_matrix
    from copeca.orchestration.run import run_single as run_single_task
    from copeca.orchestration.validation import validate_scenario
    from copeca.repos.manager import GitWorktreeManager

    # ── Detect: scenario or single task? ────────────────────────────────
    lookup_text = task.read_text()
    doc = yaml.safe_load(lookup_text)
    is_scenario = isinstance(doc, dict) and "tasks" in doc or "scenario" in task.name.lower()

    # ── Resolve signing key (opt-in tamper-evidence) at the boundary ──────
    signing_key = None
    if sign_key is not None:
        if not artifacts:
            typer.echo("Error: --sign-key requires --artifacts", err=True)
            raise typer.Exit(code=2)
        from copeca.results.signing import load_private_key_file

        try:
            signing_key = load_private_key_file(str(sign_key))
        except FileNotFoundError:
            typer.echo(f"Error: signing key not found: {sign_key}", err=True)
            raise typer.Exit(code=2) from None
        except ValueError as e:
            typer.echo(f"Error: invalid signing key: {e}", err=True)
            raise typer.Exit(code=2) from e

    repos_path = Path("repos.yaml")
    if not repos_path.exists():
        repos_path = (
            task.parent.parent / "repos.yaml" if task.parent.parent.name else Path("repos.yaml")
        )
    repos = load_repos(repos_path) if repos_path.exists() else {}

    # ── Resolve runner dirs: project-local first, then the packaged defaults.
    # The runner's CLI interface AND pricing come from <name>.yaml (config-driven
    # — no agent's flags are hardcoded here). An unknown runner fails loudly.
    runner_dirs = [task.parent.parent / "defaults" / "runners", data_path("defaults", "runners")]
    try:
        runner_cfg = load_runner(runner, runner_dirs=runner_dirs)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from e

    pricing = runner_cfg.pricing
    if pricing is not None:
        from copeca.orchestration.validation import check_pricing_staleness

        emit_staleness_warnings(check_pricing_staleness(pricing))

    if is_scenario:
        # ── Scenario mode ───────────────────────────────────────────────
        typer.echo(f"Detected scenario file: {task}")
        scenario = load_scenario(task)

        tasks_dir = task.parent.parent / "tasks" if task.parent.parent.name else Path("tasks")
        if not tasks_dir.is_dir():
            tasks_dir = data_path("tasks")
        loaded_tasks = load_tasks_from_dir(tasks_dir)
        task_names = {t.name for t in loaded_tasks}

        # Load each mode's YAML into a Mode model so run_matrix can apply its
        # integration paths. An unknown mode (no YAML) fails loudly here.
        modes_dirs = [task.parent.parent / "defaults" / "modes", data_path("defaults", "modes")]
        try:
            mode_defs = load_modes(scenario.modes, modes_dirs=modes_dirs)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e

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

        total_runs = (
            len(scenario.tasks) * len(scenario.modes) * scenario.repetitions * len(scenario.models)
        )
        typer.echo(
            f"Running scenario '{scenario.name}': "
            f"{len(scenario.tasks)} task(s) x {len(scenario.modes)} mode(s) x "
            f"{scenario.repetitions} rep(s) = {total_runs} total runs"
        )

        # Fresh results file per run — truncate so re-running the same scenario name does
        # not append onto (and mix with) a previous run's records.
        results_dir.mkdir(parents=True, exist_ok=True)
        results_path.write_text("")

        # Stream each record to disk AS it completes — crash-safe + live partial stats.
        # I/O lives here at the CLI boundary; run_matrix stays I/O-free (architecture.md §7.8).
        def _persist(record: dict) -> None:
            append_jsonl(record, results_path)
            emit_vendor_divergence_warning(extract_vendor_divergence_warning(record))

        records = run_matrix(
            scenario=scenario,
            tasks=loaded_tasks,
            modes=scenario.modes,
            runner_factory=lambda mode_name, model_name: build_runner(
                runner, timeout=timeout, runner_dirs=runner_dirs
            ),
            repo_mgr=repo_mgr,
            repos=repos,
            on_record=_persist,
            max_workers=scenario.max_workers,
            pricing=pricing,
            mode_defs=mode_defs,
            keep_worktrees=keep_worktrees,
        )

        if artifacts:
            task_by_name = {t.name: t for t in loaded_tasks}
            paths = _build_artifacts_for_records(
                records,
                task_by_name,
                repos,
                repo_mgr,
                results_dir,
                signing_key,
                keep_worktrees,
            )
            signed_note = " (signed)" if signing_key is not None else ""
            typer.echo(f"Built {len(paths)} artifact(s){signed_note} in {results_dir}")

        if verbose:
            correct_count = sum(1 for r in records if r.get("correct"))
            typer.echo(f"Results: {correct_count}/{len(records)} correct")
            typer.echo(f"Written to: {results_path}")

        if keep_worktrees:
            pool = Path("repos").resolve() / "_worktrees"
            typer.echo(
                f"Worktrees preserved under {pool} "
                "(per-arm config in each <worktree>/.copeca-arms/)"
            )
    else:
        # ── Single-task mode ────────────────────────────────────────────
        task_obj = load_task(task)

        runner_instance = build_runner(runner, timeout=timeout, runner_dirs=runner_dirs)

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
            keep_worktree=keep_worktrees,
        )

        # I/O at the boundary (architecture.md §2):
        append_jsonl(record, results_path)
        emit_vendor_divergence_warning(extract_vendor_divergence_warning(record))
        if artifacts:
            paths = _build_artifacts_for_records(
                [record],
                {task_obj.name: task_obj},
                repos,
                repo_mgr,
                Path("results"),
                signing_key,
                keep_worktrees,
            )
            signed_note = " (signed)" if signing_key is not None else ""
            for artifact_path in paths:
                typer.echo(f"Artifact: {artifact_path}{signed_note}")

        if verbose:
            typer.echo(f"correct: {record['correct']}")
            typer.echo(f"cost: ${record['total_cost_usd']:.4f}")
            typer.echo(f"duration: {record['duration_ms']}ms")

        if keep_worktrees:
            pool = Path("repos").resolve() / "_worktrees"
            typer.echo(f"Worktree preserved under {pool} for inspection")


@app.command()
def check_task(
    task_file: Path = typer.Argument(..., help="Path to an edit task YAML file"),
    repos_dir: Path = typer.Option(Path("repos"), "--repos-dir", help="Directory for git repos"),
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
    pubkey: Path = typer.Option(
        None,
        "--pubkey",
        help="Ed25519 public key PEM to verify the artifact's detached signature "
        "(real tamper-evidence). Without it, only corruption is detected.",
    ),
) -> None:
    """Verify a .copeca artifact's integrity, or check batch completeness.

    Single-artifact mode (default): recomputes the integrity manifest to detect
    corruption. The manifest alone is NOT tamper-proof — anyone who rewrites the
    zip can recompute it.

    Signature mode (--pubkey <public.pem>): additionally verifies the detached
    Ed25519 signature over the content_hash. A tampered (and manifest-recomputed)
    artifact fails here because the attacker cannot re-sign without the private
    key. Exits non-zero if the artifact is unsigned, signed by a different key, or
    its signature does not match.

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
            raise typer.Exit(code=2) from None

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

    if pubkey is not None:
        # ── Signature mode: real tamper-evidence ──────────────────────────────
        from copeca.results.signing import load_public_key_file
        from copeca.results.verification import verify_signed_artifact

        try:
            public_key = load_public_key_file(str(pubkey))
        except FileNotFoundError:
            typer.echo(f"Error: public key not found: {pubkey}", err=True)
            raise typer.Exit(code=2) from None
        except ValueError as e:
            typer.echo(f"Error: invalid public key: {e}", err=True)
            raise typer.Exit(code=2) from e

        try:
            report = verify_signed_artifact(artifact, public_key=public_key)
        except FileNotFoundError:
            typer.echo(f"Error: file not found: {artifact}", err=True)
            raise typer.Exit(code=2) from None

        signed_label = "signed" if report.signed else "unsigned"
        valid_label = "valid" if report.valid else "INVALID"
        typer.echo(f"Signature: {signed_label} / {valid_label}")
        typer.echo(f"Integrity: {'ok' if report.corruption_ok else 'CORRUPT'}")
        if report.signed and report.valid and report.corruption_ok:
            typer.echo(report.message)
            return
        typer.echo(f"FAILED: {report.message}", err=True)
        raise typer.Exit(code=1)

    from copeca.results.verification import verify_artifact

    try:
        valid, message = verify_artifact(artifact)
    except FileNotFoundError:
        typer.echo(f"Error: file not found: {artifact}", err=True)
        raise typer.Exit(code=2) from None

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

    from copeca.analysis.report import generate_report
    from copeca.analysis.stats import cost_per_correct

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

    package_tasks = data_path("tasks")
    if package_tasks.is_dir():
        dest_tasks = target / "tasks"
        if not dest_tasks.exists():
            shutil.copytree(package_tasks, dest_tasks)

    package_repos = data_path("repos.yaml")
    if package_repos.exists():
        shutil.copy2(package_repos, target / "repos.yaml")

    package_defaults = data_path("defaults")
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


@app.command(name="new-task")
def new_task(
    output: Path = typer.Argument(..., help="Path to write the scaffolded task YAML"),
) -> None:
    """Scaffold a commented task YAML skeleton to the given path.

    The skeleton contains every required field with placeholder values and a
    commented line for each optional field. Category choices are derived
    dynamically from the Category enum so this stays in sync with the model.
    """
    from copeca.config.models import Category

    categories = [c.value for c in Category]
    categories_comment = " | ".join(categories)

    skeleton = f"""\
# copeca task skeleton — fill in every required field, then run:
#   copeca validate <dir>             # schema + provenance + tool-agnosticism
#   copeca check-task <this-file>     # edit tasks only: proves the mutation bites

name: my_task_name            # required: snake_case, e.g. rg_find_matcher_trait
description: ""               # optional: one-line summary of what the task tests
source: "MySource (MIT)"      # required: provenance + license family (Apache-2.0 / MIT / CC-BY)
repo: ripgrep                 # required: key in repos.yaml
# commit: <40-char SHA>       # optional: per-task commit override (overrides repos.yaml default)
type: comprehension           # required: comprehension | edit
category: locate              # required: {categories_comment}
language: rust                # required: python | rust | go | javascript
difficulty: medium            # required: easy | medium | hard
version: 1                    # required: integer; bump on semantic changes

prompt: |
  # required: the natural-language question sent to the agent.
  # Name the INFORMATION required — never the tool or method to retrieve it.
  # Bad: "Use grep to find ..."   Good: "Find the X that ..."
  Describe what the agent must find or do.

ground_truth:
  # For comprehension tasks — string matching against agent output (case-insensitive):
  required_strings:        # every string must appear in the output
    - ExampleSymbol
  all_of:                  # completeness check: every entry must appear
    - ExampleSymbol
  forbidden_strings:       # none of these may appear (catches refusals)
    - "I cannot"
    - "unable to"
  # For edit tasks — replace the block above with:
  # test_command:          # argv; exit 0 = agent fixed the bug
  #   - python
  #   - -m
  #   - pytest
  #   - tests/test_fix.py

# mutations:               # edit tasks only: code changes that introduce a bug
#   - file: path/to/file.py
#     action: replace      # replace | delete | insert_after | create
#     find: "correct_value"
#     replace: "broken_value"
#     occurrence: 1        # optional (default 1); which occurrence to replace

# mutation_sequence:       # debug tasks only: committed steps that build git history
#   - message: "Introduce regression in foo()"
#     mutations:
#       - file: path/to/file.py
#         action: replace
#         find: "correct"
#         replace: "broken"
"""

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        typer.echo(f"Error: file already exists: {output}", err=True)
        raise typer.Exit(code=1)
    output.write_text(skeleton)
    typer.echo(f"Scaffolded task skeleton: {output}")
    typer.echo("Next steps:")
    typer.echo(f"  1. Edit {output}")
    typer.echo("  2. copeca validate <dir>")
    typer.echo("  3. copeca check-task <file>  (edit tasks only)")


if __name__ == "__main__":
    app()
