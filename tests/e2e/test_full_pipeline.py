"""Hermetic end-to-end test for copeca's measurement pipeline.

Drives the WHOLE chain through a REAL subprocess (fake_agent.py):

    run_matrix → run_single → provision_arm → SubprocessRunner
    → StreamJsonParser → compute_cost → check_correctness → record
    → generate_report

Uses a local git repo (no network), a deterministic fake agent (no LLM,
no API), and hand-computed expected costs so every assertion is provable.

NO mocks of runner / parser / cost / grader.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from copeca.analysis.report import generate_report
from copeca.config.models import (
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Mode,
    Repo,
    Scenario,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_matrix
from copeca.repos.manager import GitWorktreeManager
from copeca.runners.parsers.stream_json import StreamJsonParser
from copeca.runners.subprocess import SubprocessRunner

# ── Constants (single source of truth for the fake agent's token budget) ──────

FAKE_AGENT = Path(__file__).parent / "fake_agent.py"

# Token counts emitted by fake_agent.py (must stay in sync with that file).
INPUT_TOKENS = 1000
OUTPUT_TOKENS = 500
CACHE_CREATION_TOKENS = 200
CACHE_READ_TOKENS = 300

# Pricing rates (USD per 1M tokens) — chosen to make hand-computation trivial.
PRICING = {
    "input": 3.0,
    "cache_creation": 3.75,
    "cache_read": 0.30,
    "output": 15.0,
}

# Hand-computed cost per single fake run:
#   (1000×3.0 + 200×3.75 + 300×0.30 + 500×15.0) / 1_000_000
#   = (3000 + 750 + 90 + 7500) / 1_000_000
#   = 11340 / 1_000_000
#   = 0.01134
EXPECTED_COST_PER_RUN = 0.01134

MODEL = "fake-model"

# The fake agent's deterministic answer contains these strings — grading passes.
REQUIRED_STRINGS = [
    "Matcher trait",
    "src/matcher.rs",
    "find_at",
]

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def local_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal local git repo and return (path, commit_sha).

    The repo contains a Rust file with a `Matcher` trait and a `find_at`
    method so the fake agent's hardcoded answer matches the ground truth.
    """
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()

    # Init repo with a known identity (no global git config needed).
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@copeca.test"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "copeca e2e"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    # Source file: contains the Matcher trait + find_at method.
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "matcher.rs").write_text(
        "pub trait Matcher {\n    fn find_at(&self, haystack: &[u8], at: usize) -> Option<usize>;\n}\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    # Capture the HEAD SHA.
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()

    return repo_dir, sha


@pytest.fixture()
def repo_mgr(tmp_path: Path) -> GitWorktreeManager:
    """GitWorktreeManager rooted in a dedicated subdirectory of tmp_path."""
    return GitWorktreeManager(tmp_path / "worktrees")


@pytest.fixture()
def repos(local_repo: tuple[Path, str]) -> dict[str, Repo]:
    """Repos dict mapping 'local-test-repo' to the local clone."""
    repo_dir, sha = local_repo
    return {
        "local-test-repo": Repo(
            url=str(repo_dir),  # local path — git clone --bare works on it
            commit=sha,
            language=Language.rust,
            toolchain={},       # empty: verify_toolchain only checks git
            setup_command=[],
        )
    }


@pytest.fixture()
def task() -> Task:
    """A comprehension task whose required_strings match the fake agent's answer."""
    return Task(
        name="find-matcher-trait",
        description="Find the Matcher trait definition",
        source="e2e-test",
        repo="local-test-repo",
        type=TaskType.comprehension,
        language=Language.rust,
        difficulty=Difficulty.easy,
        prompt="Where is the Matcher trait defined and what method does it declare?",
        ground_truth=ComprehensionGroundTruth(
            required_strings=REQUIRED_STRINGS,
        ),
    )


@pytest.fixture()
def scenario(task: Task) -> Scenario:
    """Scenario: two modes × 2 repetitions so the matrix has 4 records."""
    return Scenario(
        name="e2e-hermetic",
        description="Hermetic pipeline test",
        tasks=[task.name],
        modes=["baseline", "exp"],
        models=[MODEL],
        repetitions=2,
        timeout_seconds=30,
    )


@pytest.fixture()
def mode_defs() -> dict[str, Mode]:
    """Mode definitions — baseline uses tools-only; exp adds an env marker."""
    return {
        "baseline": Mode(
            name="baseline",
            description="No tool augmentation",
            tools=["bash"],     # at_least_one_path_or_tool_change satisfied
        ),
        "exp": Mode(
            name="exp",
            description="Experimental arm with env marker",
            env={"COPECA_E2E_MARKER": "exp-active"},
        ),
    }


# ── Runner factory ─────────────────────────────────────────────────────────────


def _make_runner(_mode: str, _model: str) -> SubprocessRunner:
    """Factory: returns a real SubprocessRunner backed by the fake agent script.

    The command built by build_command will be:
        [sys.executable, <fake_agent.py>, "--", <prompt>]

    fake_agent.py's _extract_prompt() finds "--" and takes everything after it.
    """
    return SubprocessRunner(
        name="fake-agent",
        cli=sys.executable,
        default_args=[str(FAKE_AGENT)],
        arg_map={"prompt_separator": "--"},
        parser=StreamJsonParser(),
        timeout=30,
    )


# ── The test ──────────────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_full_pipeline(
    local_repo: tuple[Path, str],
    repo_mgr: GitWorktreeManager,
    repos: dict[str, Repo],
    task: Task,
    scenario: Scenario,
    mode_defs: dict[str, Mode],
) -> None:
    """Drive the entire measurement pipeline end-to-end with no mocks."""

    # ── 1. Pricing dict keyed by model name (run.py uses pricing.get(model)) ──
    pricing = {MODEL: PRICING}

    # ── 2. Run the full matrix ─────────────────────────────────────────────────
    records = run_matrix(
        scenario=scenario,
        tasks=[task],
        modes=scenario.modes,
        runner_factory=_make_runner,
        repo_mgr=repo_mgr,
        repos=repos,
        results_path=None,
        max_workers=1,          # sequential — deterministic ordering
        pricing=pricing,
        mode_defs=mode_defs,
    )

    # ── 3. Basic shape ─────────────────────────────────────────────────────────
    # 1 task × 2 modes × 1 model × 2 repetitions = 4 records
    assert len(records) == 4, f"Expected 4 records, got {len(records)}: {records}"

    modes_seen = {r["mode"] for r in records}
    assert modes_seen == {"baseline", "exp"}, f"Unexpected modes: {modes_seen}"

    # ── 4. Per-record assertions ───────────────────────────────────────────────
    for rec in records:
        # Real subprocess was spawned and parsed — grading ran on real output.
        assert rec["correct"] is True, (
            f"Expected correct=True for {rec['mode']} rep={rec['repetition']}, "
            f"got result_text={rec.get('result_text', '')!r}"
        )

        # Cost computed from real token counts × pricing (not mocked).
        assert rec["total_cost_usd"] > 0, (
            f"total_cost_usd must be > 0, got {rec['total_cost_usd']}"
        )
        assert abs(rec["total_cost_usd"] - EXPECTED_COST_PER_RUN) < 1e-9, (
            f"Cost mismatch: expected {EXPECTED_COST_PER_RUN}, "
            f"got {rec['total_cost_usd']}"
        )

        # Repetition field is set by run_matrix.
        assert "repetition" in rec, "record must carry repetition"
        assert rec["repetition"] in (0, 1), (
            f"repetition out of range: {rec['repetition']}"
        )

        # Mode names must match the scenario definition.
        assert rec["mode"] in ("baseline", "exp"), f"Unexpected mode: {rec['mode']}"

        # Tokens are aggregated from real parsed stream-json output.
        assert rec["input_tokens"] == INPUT_TOKENS
        assert rec["output_tokens"] == OUTPUT_TOKENS
        assert rec["cache_creation_tokens"] == CACHE_CREATION_TOKENS
        assert rec["cache_read_tokens"] == CACHE_READ_TOKENS

    # ── 5. Repetition coverage: 0 and 1 appear for each mode ──────────────────
    for mode_name in ("baseline", "exp"):
        mode_recs = [r for r in records if r["mode"] == mode_name]
        assert len(mode_recs) == 2, (
            f"Expected 2 records for mode={mode_name}, got {len(mode_recs)}"
        )
        reps = {r["repetition"] for r in mode_recs}
        assert reps == {0, 1}, f"Expected reps {{0,1}} for {mode_name}, got {reps}"

    # ── 6. Env marker confirms provision_arm wired Mode.env to the process ─────
    exp_recs = [r for r in records if r["mode"] == "exp"]
    for rec in exp_recs:
        assert "exp-active" in rec.get("result_text", ""), (
            "Mode.env COPECA_E2E_MARKER=exp-active must appear in the fake "
            "agent's answer (env-marker=exp-active). result_text was: "
            f"{rec.get('result_text', '')!r}"
        )

    baseline_recs = [r for r in records if r["mode"] == "baseline"]
    for rec in baseline_recs:
        # Baseline has no env override — marker value is 'absent'.
        assert "env-marker=absent" in rec.get("result_text", ""), (
            "Baseline arm must not inject COPECA_E2E_MARKER. result_text: "
            f"{rec.get('result_text', '')!r}"
        )

    # ── 7. Report generation ───────────────────────────────────────────────────
    report = generate_report(records)

    # Report must be non-empty and contain the standard sections.
    assert "## Copeca Report" in report
    assert "### Cost Per Correct Answer" in report
    assert "### Per-Task Cost" in report

    # Two modes → delta line is present.
    assert "**Delta:**" in report, (
        "Report must contain a Delta headline when two modes are present"
    )

    # Cost-per-correct headline contains a dollar amount.
    assert "$" in report, "Report must contain cost-per-correct dollar values"

    # Per-task table must name our task.
    assert "find-matcher-trait" in report, (
        "Per-task table must include the task name"
    )

    # CI bracket appears because we have per-task deltas from multiple tasks.
    # With 1 task and 2 modes the bootstrap may or may not produce a CI,
    # but the delta line itself must exist.
    assert "baseline" in report and "exp" in report, (
        "Both mode names must appear in the report"
    )


@pytest.mark.e2e
def test_cli_artifact_path_builds_one_per_matrix_record(
    tmp_path: Path,
    repo_mgr: GitWorktreeManager,
    repos: dict[str, Repo],
    task: Task,
    scenario: Scenario,
    mode_defs: dict[str, Mode],
) -> None:
    """SD-M: the scenario-mode --artifacts path builds one real .copeca per record.

    This is the integration proof for the bug fix: a real run_matrix produces real
    records, then the CLI's shared artifact helper (_build_artifacts_for_records) is
    called with the EXACT inputs cli.py's scenario block passes — real repos, a real
    GitWorktreeManager (real git worktrees), task_by_name from the loaded tasks. It
    must emit one valid .copeca zip per record, not silently no-op as before.
    """
    import zipfile

    from copeca.cli import _build_artifacts_for_records

    records = run_matrix(
        scenario=scenario,
        tasks=[task],
        modes=scenario.modes,
        runner_factory=_make_runner,
        repo_mgr=repo_mgr,
        repos=repos,
        results_path=None,
        max_workers=1,
        pricing={MODEL: PRICING},
        mode_defs=mode_defs,
    )
    assert len(records) == 4  # 1 task × 2 modes × 2 reps

    # Mirror cli.py's scenario block exactly.
    out_dir = tmp_path / "artifacts-out"
    out_dir.mkdir()
    task_by_name = {task.name: task}
    paths = _build_artifacts_for_records(
        records, task_by_name, repos, repo_mgr, out_dir, None, False
    )

    # One artifact per record — the whole batch is evidence, not just single-task.
    assert len(paths) == len(records)
    zips = sorted(out_dir.glob("*.copeca.zip"))
    assert len(zips) == len(records)
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            assert "result.json" in names
            assert "manifest.json" in names
    # Filenames encode each (mode, rep) so nothing is overwritten.
    names = {z.name for z in zips}
    assert any("baseline" in n and "rep00" in n for n in names)
    assert any("exp" in n and "rep01" in n for n in names)
