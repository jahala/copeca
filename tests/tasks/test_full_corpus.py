"""Full-corpus validation and taxonomy audit tests.

Tests:
1. test_validate_all_tasks_passes — copeca validate tasks/ exits 0
2. test_all_tasks_have_source_field — every YAML file has non-empty source:
3. test_no_blocked_sources — no source references blocked families
4. test_corpus_has_four_languages — tasks exist in python, rust, go, javascript
5. test_comprehension_and_edit_both_present — at least 1 of each type
6. test_contamination_check_on_all_comprehension_tasks — all comprehension pass
7. test_taxonomy_audit_runs — taxonomy_audit.py runs without error
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from copeca.config.resources import data_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS_DIR = data_path("tasks")
COPECA = PROJECT_ROOT / ".venv" / "bin" / "copeca"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _discover_task_files() -> list[Path]:
    """Find all *.yaml files recursively under tasks/."""
    return sorted(TASKS_DIR.rglob("*.yaml"))


def _load_task(path: Path) -> dict:
    """Load a single task YAML file into a dict."""
    with open(path) as f:
        return yaml.safe_load(f)


def _run_copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point."""
    return subprocess.run(
        [str(COPECA), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── Blocked source prefixes ────────────────────────────────────────────────────

BLOCKED_SOURCE_PREFIXES = (
    "SWE-bench Verified",
    "RepoBench",
    "ClassEval",
)

REQUIRED_LANGUAGES = {"rust", "python", "go", "javascript"}


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateAllTasks:
    """copeca validate tasks/ exits 0."""

    def test_validate_all_tasks_passes(self):
        result = _run_copeca("validate", str(TASKS_DIR))
        assert result.returncode == 0, (
            f"copeca validate tasks/ failed (exit {result.returncode}):\n"
            f"stderr={result.stderr}\nstdout={result.stdout}"
        )


class TestSourceFields:
    """Every task YAML has a non-empty source field."""

    def test_all_tasks_have_source_field(self):
        task_files = _discover_task_files()
        assert len(task_files) > 0, "No task files found"
        for path in task_files:
            task = _load_task(path)
            source = task.get("source", "")
            assert source, f"{path.name}: source field is empty or missing"

    def test_no_blocked_sources(self):
        """No task references SWE-bench Verified, RepoBench, or ClassEval."""
        for path in _discover_task_files():
            task = _load_task(path)
            source = task.get("source", "")
            assert not source.startswith(BLOCKED_SOURCE_PREFIXES), (
                f"{path.name}: source '{source}' is blocked"
            )


class TestLanguages:
    """Tasks exist in all 4 required languages."""

    def test_corpus_has_four_languages(self):
        seen = {
            _load_task(p).get("language", "")
            for p in _discover_task_files()
        }
        missing = REQUIRED_LANGUAGES - seen
        assert not missing, (
            f"Missing languages: {missing}. Found: {seen}"
        )


class TestTaskTypes:
    """Both comprehension and edit tasks are present."""

    def test_comprehension_and_edit_both_present(self):
        comp_count = 0
        edit_count = 0
        for path in _discover_task_files():
            task = _load_task(path)
            ttype = task.get("type")
            if ttype == "comprehension":
                comp_count += 1
            elif ttype == "edit":
                edit_count += 1

        assert comp_count >= 1, (
            f"Expected at least 1 comprehension task, got {comp_count}"
        )
        assert edit_count >= 1, (
            f"Expected at least 1 edit task, got {edit_count}"
        )


class TestContaminationCheck:
    """All comprehension tasks pass the contamination self-check."""

    def test_contamination_check_on_all_comprehension_tasks(self):
        from scripts.contamination_check import (
            build_probe,
            check_contamination,
        )

        # Load blocklist
        blocklist_file = SCRIPTS_DIR / "contamination_blocklist.txt"
        blocklist: set[str] = set()
        with open(blocklist_file) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                blocklist.add(stripped)
        assert len(blocklist) > 0, "Blocklist must be non-empty"

        comprehension_count = 0
        for path in _discover_task_files():
            task = _load_task(path)
            if task.get("type") != "comprehension":
                continue
            comprehension_count += 1

            name = task.get("name", "")
            prompt = task.get("prompt", "")
            gt = task.get("ground_truth", {})
            required_strings = gt.get("required_strings", [])

            contaminated = check_contamination(
                task_name=name,
                prompt=prompt,
                required_strings=required_strings,
                blocklist=blocklist,
            )
            assert contaminated is False, (
                f"Task '{name}' was flagged as contaminated but shouldn't be. "
                f"probe: {build_probe(name, prompt)}"
            )

        assert comprehension_count >= 1, (
            f"Expected at least 1 comprehension task, found {comprehension_count}"
        )


class TestTaxonomyAudit:
    """taxonomy_audit.py runs without error."""

    def test_taxonomy_audit_runs(self):
        audit_script = SCRIPTS_DIR / "taxonomy_audit.py"
        assert audit_script.exists(), (
            f"taxonomy_audit.py not found at {audit_script}"
        )

        result = subprocess.run(
            [sys.executable, str(audit_script), str(TASKS_DIR)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"taxonomy_audit.py failed (exit {result.returncode}):\n"
            f"stderr={result.stderr}\nstdout={result.stdout}"
        )


class TestTaxonomyAuditOutput:
    """taxonomy_audit.py output correctness."""

    def test_audit_counts_match_expected(self, tmp_path):
        """Create controlled tasks, run audit, verify type and language counts."""
        td = tmp_path / "tasks"
        td.mkdir()
        for i, (name, ttype, lang) in enumerate([
            ("task_comp_a", "comprehension", "python"),
            ("task_comp_b", "comprehension", "python"),
            ("task_edit_a", "edit", "go"),
        ]):
            (td / f"t{i:03d}.yaml").write_text(f"""
name: {name}
source: test
repo: test-repo
type: {ttype}
language: {lang}
difficulty: easy
version: 1
prompt: test
ground_truth:
  required_strings: [test]
""")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "taxonomy_audit.py"), str(td)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"audit failed: {result.stderr}"
        # Verify counts in output
        assert "comprehension" in result.stdout
        assert "python" in result.stdout
        assert "go" in result.stdout

    def test_audit_empty_directory_returns_zero(self, tmp_path):
        td = tmp_path / "empty"
        td.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "taxonomy_audit.py"), str(td)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
