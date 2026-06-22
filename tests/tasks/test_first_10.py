"""Test the first 10 copeca task YAML files for correctness and completeness.

Architecture: no mocking — this is a validation test that runs copeca validate
as a subprocess and verifies YAML content directly.
"""

import subprocess
import sys
from pathlib import Path

import yaml

from copeca.config.resources import data_path

TASKS_DIR = data_path("tasks")

# Approved source families — sources that tasks may draw from.
# Each entry is a prefix that task.source must start with.
APPROVED_SOURCE_PREFIXES = (
    "SWE-QA",  # Apache-2.0 — QA tasks
    "SCBench",  # MIT — function retrieval
    "Long Code Arena",  # Apache-2.0 — bug localization
    "CrossCodeEval",  # Apache-2.0 — repository discovery
    "SWE-bench-Live",  # MIT — time-gated edits
    "Terminal-Bench 2.0",  # Apache-2.0 — CLI tasks
    "tilth-benchmark",  # MIT — migrated tasks
    "copeca-control",  # MIT — first-party tool-neutral control tasks (#52)
)
# Sources that are explicitly disallowed (NWC/NC/ND, contaminated, deprecated).
BLOCKED_SOURCE_PREFIXES = (
    "SWE-bench Verified",
    "RepoBench",
    "ClassEval",
    "DevEval",
    "CoderEval",
)

# All 4 languages from the spec must be represented.
REQUIRED_LANGUAGES = {"rust", "python", "go", "javascript"}


def _discover_task_files() -> list[Path]:
    """Find all *.yaml files recursively under tasks/. Does NOT filter by name."""
    return sorted(TASKS_DIR.rglob("*.yaml"))


def _load_task(path: Path) -> dict:
    """Load a single task YAML file into a dict."""
    with open(path) as f:
        return yaml.safe_load(f)


class TestValidation:
    def test_all_shipped_tasks_validate(self):
        """Every *.yaml file in tasks/ passes copeca validate."""
        task_files = _discover_task_files()
        assert len(task_files) > 0, "No task files found"

        for task_dir in sorted({f.parent for f in task_files}):
            result = subprocess.run(
                [sys.executable, "-m", "copeca", "validate", str(task_dir)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (
                f"copeca validate failed for {task_dir}:\n{result.stderr}"
            )


class TestSourceFields:
    def test_source_fields_from_approved_families(self):
        """Every task's source references an approved source family."""
        for path in _discover_task_files():
            task = _load_task(path)
            source = task.get("source", "")
            assert source, f"{path.name}: source field is empty"
            assert source.startswith(APPROVED_SOURCE_PREFIXES), (
                f"{path.name}: source '{source}' does not start with an approved prefix"
            )

    def test_no_blocked_sources(self):
        """No task references SWE-bench Verified, RepoBench, or ClassEval."""
        for path in _discover_task_files():
            task = _load_task(path)
            source = task.get("source", "")
            assert not source.startswith(BLOCKED_SOURCE_PREFIXES), (
                f"{path.name}: source '{source}' is blocked"
            )

    def test_approved_and_blocked_have_no_overlap(self):
        """No source family appears in both APPROVED and BLOCKED lists."""
        approved = set(APPROVED_SOURCE_PREFIXES)
        blocked = set(BLOCKED_SOURCE_PREFIXES)
        overlap = approved & blocked
        assert not overlap, f"Overlap between APPROVED and BLOCKED source prefixes: {overlap}"


class TestComprehensionTasks:
    def test_comprehension_tasks_have_required_strings(self):
        """All comprehension tasks have non-empty required_strings in ground_truth."""
        comprehension_count = 0
        for path in _discover_task_files():
            task = _load_task(path)
            if task.get("type") != "comprehension":
                continue
            comprehension_count += 1
            gt = task.get("ground_truth", {})
            required = gt.get("required_strings", [])
            assert isinstance(required, list), f"{path.name}: required_strings must be a list"
            assert len(required) > 0, (
                f"{path.name}: comprehension task must have at least one required_string"
            )

        assert comprehension_count >= 5, (
            f"Expected at least 5 comprehension tasks, found {comprehension_count}"
        )


class TestEditTasks:
    def test_edit_tasks_have_mutations_and_test_command(self):
        """All edit tasks have a non-empty mutations or mutation_sequence, plus a test_command.

        debug-category edit tasks use mutation_sequence (committed history) instead of
        the plain mutations list — both are valid ways to introduce a regression.
        """
        edit_count = 0
        for path in _discover_task_files():
            task = _load_task(path)
            if task.get("type") != "edit":
                continue
            edit_count += 1

            mutations = task.get("mutations", [])
            mutation_sequence = task.get("mutation_sequence", [])
            assert isinstance(mutations, list), f"{path.name}: mutations must be a list"
            assert isinstance(mutation_sequence, list), (
                f"{path.name}: mutation_sequence must be a list"
            )
            assert len(mutations) > 0 or len(mutation_sequence) > 0, (
                f"{path.name}: edit task must have at least one mutation "
                f"(in 'mutations' or 'mutation_sequence')"
            )

            gt = task.get("ground_truth", {})
            test_cmd = gt.get("test_command", [])
            assert isinstance(test_cmd, list), f"{path.name}: test_command must be a list"
            assert len(test_cmd) > 0, f"{path.name}: edit task must have a non-empty test_command"

        assert edit_count >= 5, f"Expected at least 5 edit tasks, found {edit_count}"


class TestCounts:
    def test_count_at_least_five_each(self):
        """At least 5 comprehension and 5 edit tasks."""
        comp = sum(
            1 for p in _discover_task_files() if _load_task(p).get("type") == "comprehension"
        )
        edit = sum(1 for p in _discover_task_files() if _load_task(p).get("type") == "edit")
        assert comp >= 5, f"Expected >= 5 comprehension tasks, got {comp}"
        assert edit >= 5, f"Expected >= 5 edit tasks, got {edit}"


class TestLanguages:
    def test_languages_include_rust_python_go_javascript(self):
        """Task files cover all 4 required languages."""
        seen = {_load_task(p).get("language", "") for p in _discover_task_files()}
        missing = REQUIRED_LANGUAGES - seen
        assert not missing, f"Missing languages: {missing}. Found: {seen}"


class TestRepos:
    def test_all_repos_referenced_exist_in_repos_yaml(self):
        """Every task's repo key exists in repos.yaml."""
        repos_yaml = data_path("repos.yaml")
        with open(repos_yaml) as f:
            repo_data = yaml.safe_load(f)
        known_repos = set(repo_data.keys())

        for path in _discover_task_files():
            task = _load_task(path)
            repo = task.get("repo", "")
            assert repo, f"{path.name}: repo field is empty"
            assert repo in known_repos, (
                f"{path.name}: repo '{repo}' not found in repos.yaml. "
                f"Available: {sorted(known_repos)}"
            )
