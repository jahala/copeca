"""Test contamination self-check for comprehension tasks."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.contamination_check import (
    build_probe,
    check_contamination,
    check_source_provenance,
    load_blocked_sources,
)

from copeca.config.resources import data_path

TASKS_DIR = data_path("tasks")
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
BLOCKLIST_FILE = SCRIPTS_DIR / "contamination_blocklist.txt"


def _load_blocklist() -> set[str]:
    """Load the contamination blocklist from file, stripping comments and blanks."""
    patterns: set[str] = set()
    with open(BLOCKLIST_FILE) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            patterns.add(stripped)
    return patterns


def _discover_comprehension_tasks() -> list[dict]:
    """Load all comprehension task YAML files."""
    tasks: list[dict] = []
    for path in sorted(TASKS_DIR.rglob("*.yaml")):
        with open(path) as f:
            task = yaml.safe_load(f)
        if task.get("type") == "comprehension":
            tasks.append(task)
    return tasks


# ── probe tests ───────────────────────────────────────────────────────────────


class TestBuildProbe:
    def test_build_probe_returns_task_name_and_first_10_words(self):
        task_name = "t001_find_matcher_trait"
        prompt = "Find the Matcher trait definition in the ripgrep codebase and list all structs that implement it. For each implementor, note which crate it lives in and what methods it provides."
        probe = build_probe(task_name, prompt)
        assert task_name in probe
        # First 10 words of the prompt
        expected_prefix = "Find the Matcher trait definition in the ripgrep codebase and"
        assert probe.startswith(f"{task_name} {expected_prefix}")

    def test_build_probe_handles_short_prompt(self):
        task_name = "my_task"
        prompt = "only three words"
        probe = build_probe(task_name, prompt)
        assert probe == "my_task only three words"


# ── clean task tests ──────────────────────────────────────────────────────────


class TestCheckContamination:
    def test_clean_task_passes_self_check(self):
        """A task with clean name/prompt/strings returns False (not contaminated)."""
        blocklist = {"swe-bench-verified", "humaneval_", "mbpp_"}
        result = check_contamination(
            task_name="t001_find_matcher_trait",
            prompt="Find the Matcher trait definition in the ripgrep codebase.",
            required_strings=["Matcher", "trait", "RegexMatcher"],
            blocklist=blocklist,
        )
        assert result is False

    def test_swebench_verified_prefix_is_flagged(self):
        """Task with name starting with 'swe-bench-verified' is flagged."""
        blocklist = {"swe-bench-verified", "humaneval_", "mbpp_"}
        result = check_contamination(
            task_name="swe-bench-verified_123",
            prompt="Some prompt text for the task.",
            required_strings=["answer"],
            blocklist=blocklist,
        )
        assert result is True

    def test_blocklist_pattern_in_probe_flags_task(self):
        """Probe text containing a blocklist substring flags the task."""
        blocklist = {"humaneval_"}
        # The probe will be: task_name + first 10 words of prompt
        # Task name itself starts with humaneval_
        result = check_contamination(
            task_name="humaneval_complete",
            prompt="Write a function that solves the two-sum problem.",
            required_strings=["solution"],
            blocklist=blocklist,
        )
        assert result is True

    def test_empty_blocklist_never_flags(self):
        """Empty blocklist -> all tasks pass."""
        result = check_contamination(
            task_name="swe-bench-verified_123",
            prompt="The humaneval_ benchmark includes contaminated data.",
            required_strings=["swe-bench-verified", "humaneval_"],
            blocklist=set(),
        )
        assert result is False

    def test_leaked_output_in_required_strings_is_flagged(self):
        """A blocklist pattern appearing in required_strings flags the task."""
        blocklist = {"mbpp_"}
        result = check_contamination(
            task_name="t999_custom_task",
            prompt="Analyze the code and describe what mbpp_ prefix means.",
            required_strings=["some_output", "mbpp_solution_fragment"],
            blocklist=blocklist,
        )
        assert result is True

    def test_case_insensitive_matching(self):
        """Blocklist matching is case-insensitive."""
        blocklist = {"SWE-BENCH-VERIFIED"}
        result = check_contamination(
            task_name="swe-bench-verified_abc",
            prompt="Some prompt",
            required_strings=["answer"],
            blocklist=blocklist,
        )
        assert result is True


# ── existing tasks test ───────────────────────────────────────────────────────


class TestExistingComprehensionTasks:
    def test_all_existing_comprehension_tasks_pass(self):
        """Load the existing comprehension tasks, check each one passes (not contaminated)."""
        blocklist = _load_blocklist()
        assert len(blocklist) > 0, "Blocklist must be non-empty"

        tasks = _discover_comprehension_tasks()
        assert len(tasks) >= 5, (
            f"Expected at least 5 comprehension tasks, found {len(tasks)}"
        )

        for task in tasks:
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


# ── blocklist file test ───────────────────────────────────────────────────────


class TestBlocklistFile:
    def test_blocklist_file_exists_and_has_entries(self):
        """Blocklist file exists and contains known patterns."""
        assert BLOCKLIST_FILE.exists(), (
            f"Blocklist file not found at {BLOCKLIST_FILE}"
        )

        patterns = _load_blocklist()
        assert len(patterns) > 0, "Blocklist must have at least one entry"

        # Verify the key known patterns are present
        assert "swe-bench-verified" in patterns, (
            "swe-bench-verified must be in blocklist"
        )
        assert "humaneval_" in patterns, (
            "humaneval_ must be in blocklist"
        )
        assert "mbpp_" in patterns, (
            "mbpp_ must be in blocklist"
        )


# ── provenance / source-benchmark check tests ─────────────────────────────────


class TestCheckSourceProvenance:
    """Tests for check_source_provenance — pure function, no I/O."""

    def test_blocked_source_benchmark_is_flagged(self):
        """A task whose source field names a blocked benchmark is flagged."""
        blocked = {"SWE-bench Verified", "RepoBench", "ClassEval", "DevEval", "CoderEval"}
        # Exact match (as it appears in the task YAML)
        flagged, reason = check_source_provenance("SWE-bench Verified (MIT)", blocked)
        assert flagged is True
        assert "SWE-bench Verified" in reason

    def test_clean_source_passes(self):
        """A task from a non-blocked source passes the provenance check."""
        blocked = {"SWE-bench Verified", "RepoBench", "ClassEval", "DevEval", "CoderEval"}
        flagged, reason = check_source_provenance("SWE-QA (Apache-2.0)", blocked)
        assert flagged is False
        assert reason == ""

    def test_all_blocked_benchmarks_are_flagged(self):
        """Each entry in the block-list is individually detected."""
        blocked = {"SWE-bench Verified", "RepoBench", "ClassEval", "DevEval", "CoderEval"}
        samples = [
            "SWE-bench Verified (MIT)",
            "RepoBench",
            "ClassEval (CC BY-SA 4.0)",
            "DevEval (Apache-2.0)",
            "CoderEval (Apache-2.0)",
        ]
        for source in samples:
            flagged, _ = check_source_provenance(source, blocked)
            assert flagged is True, f"Expected {source!r} to be flagged"

    def test_empty_blocked_set_never_flags(self):
        """Empty blocked set — every source passes."""
        flagged, _ = check_source_provenance("SWE-bench Verified (MIT)", set())
        assert flagged is False

    def test_matching_is_case_insensitive(self):
        """Source matching is case-insensitive."""
        blocked = {"SWE-bench Verified"}
        flagged, _ = check_source_provenance("swe-bench verified (MIT)", blocked)
        assert flagged is True

    def test_partial_match_within_source_string(self):
        """Blocked benchmark name appearing anywhere in source field is flagged."""
        blocked = {"ClassEval"}
        # Source field has the benchmark name plus a licence suffix
        flagged, _ = check_source_provenance("ClassEval (CC BY-SA 4.0)", blocked)
        assert flagged is True


class TestLoadBlockedSources:
    """Tests for load_blocked_sources — reads contamination_blocklist.txt."""

    def test_returns_expected_blocked_benchmarks(self):
        """load_blocked_sources reads the blocklist file and returns the five benchmarks."""
        sources = load_blocked_sources(BLOCKLIST_FILE)
        expected = {"SWE-bench Verified", "RepoBench", "ClassEval", "DevEval", "CoderEval"}
        assert expected.issubset(sources), (
            f"Missing blocked sources: {expected - sources}"
        )

    def test_real_corpus_tasks_all_pass_provenance_check(self):
        """All 16 real tasks have non-blocked sources and pass provenance check."""
        blocked = load_blocked_sources(BLOCKLIST_FILE)
        all_tasks: list[dict] = []
        for path in sorted(TASKS_DIR.rglob("*.yaml")):
            with open(path) as f:
                all_tasks.append(yaml.safe_load(f))

        assert len(all_tasks) >= 16, (
            f"Expected at least 16 tasks, found {len(all_tasks)}"
        )

        for task in all_tasks:
            source = task.get("source", "")
            flagged, reason = check_source_provenance(source, blocked)
            assert flagged is False, (
                f"Task '{task.get('name')}' source {source!r} was incorrectly blocked: {reason}"
            )
