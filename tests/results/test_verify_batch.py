"""Test batch verification — directory-wide .copeca integrity scan."""

import zipfile
from pathlib import Path

from copeca.results.artifact import build_artifact
from copeca.results.verification import verify_batch


def _make_zip(record: dict, worktree: Path, output_dir: Path) -> Path:
    """Helper to build a valid .copeca zip."""
    return build_artifact(record, worktree, output_dir)


def _tamper_zip(src: Path, dst: Path, filename: str, new_content: bytes) -> None:
    """Copy a zip, replacing one file's content."""
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w") as zout:  # noqa: SIM117
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == filename:
                data = new_content
            zout.writestr(item, data)


class TestVerifyBatch:
    def test_batch_all_authentic_reports_counts(self, tmp_path):
        """All authentic zips in a directory should report correct counts."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        for i in range(3):
            record = {"task": f"task_{i}", "mode": "baseline", "model": "test"}
            _make_zip(record, worktree, output_dir)

        result = verify_batch(output_dir)

        assert result["authentic"] == 3
        assert result["tampered"] == []
        assert result["missing"] == 0

    def test_batch_with_tampered_zip_reports_it(self, tmp_path):
        """A tampered zip in the directory must be reported in the tampered list."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Build two authentic zips
        for i in range(2):
            record = {"task": f"good_{i}", "mode": "baseline", "model": "test"}
            _make_zip(record, worktree, output_dir)

        # Build a zip, then tamper it (creating a separate tampered copy, remove original)
        record = {"task": "bad_task", "mode": "baseline", "model": "test"}
        good_path = _make_zip(record, worktree, output_dir)

        tampered_path = output_dir / "bad_task__baseline__test.tampered.copeca.zip"
        _tamper_zip(good_path, tampered_path, "result.json", b'{"tampered": true}')
        # Remove the original good version so only tampered one remains for this task
        good_path.unlink()

        result = verify_batch(output_dir)

        assert result["authentic"] == 2
        assert len(result["tampered"]) >= 1
        assert result["missing"] == 0

    def test_batch_empty_directory_returns_zeros(self, tmp_path):
        """An empty directory should report zero results."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = verify_batch(empty_dir)

        assert result["authentic"] == 0
        assert result["tampered"] == []
        assert result["missing"] == 0

    def test_batch_ignores_non_zip_files(self, tmp_path):
        """Non-.copeca.zip files in the directory should be ignored."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        record = {"task": "only_good", "mode": "baseline", "model": "test"}
        _make_zip(record, worktree, output_dir)

        # Add non-zip files that should be ignored
        (output_dir / "results.jsonl").write_text('{"task": "test"}')
        (output_dir / "README.md").write_text("# Results")
        (output_dir / "random.txt").write_text("not a zip")

        result = verify_batch(output_dir)

        assert result["authentic"] == 1
        assert result["tampered"] == []


class TestVerifyBatchWithScenario:
    """Tests for verify_batch missing count computation with scenario param."""

    def test_batch_with_scenario_does_not_hardcode_missing(self, tmp_path):
        """With scenario providing expected identities, missing is the absent subset."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Scenario expects 3 tasks × 1 mode × 1 model × 2 reps = 6 runs.
        # Provide only t1/rep00 and t2/rep00 (2 of 6).
        for task_name in ("t1", "t2"):
            record = {"task": task_name, "mode": "baseline", "model": "test-model", "repetition": 0}
            _make_zip(record, worktree, output_dir)

        scenario = Scenario(
            name="test_scenario",
            tasks=["t1", "t2", "t3"],
            modes=["baseline"],
            models=["test-model"],
            repetitions=2,
        )

        result = verify_batch(output_dir, scenario=scenario)

        assert result["authentic"] == 2
        assert result["tampered"] == []
        assert result["missing"] == 4  # 6 expected - 2 matched by identity = 4 missing

    def test_batch_without_scenario_defaults_missing_zero(self, tmp_path):
        """No scenario provided → missing=0 (graceful, cannot compute)."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        record = {"task": "only_task", "mode": "baseline", "model": "test"}
        _make_zip(record, worktree, output_dir)

        result = verify_batch(output_dir)

        assert result["authentic"] == 1
        assert result["tampered"] == []
        assert result["missing"] == 0  # graceful default when no scenario

    def test_batch_empty_dir_with_scenario_reports_all_missing(self, tmp_path):
        """Empty dir with scenario → all expected runs reported as missing."""
        from copeca.config.models import Scenario

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        scenario = Scenario(
            name="empty_scenario",
            tasks=["t1", "t2"],
            modes=["baseline"],
            models=["claude-sonnet-4-6"],
            repetitions=3,
        )

        result = verify_batch(empty_dir, scenario=scenario)

        assert result["authentic"] == 0
        assert result["tampered"] == []
        assert result["missing"] == 6  # 2*1*1*3 = 6 expected, 0 actual

    def test_batch_actual_exceeds_expected_missing_is_zero(self, tmp_path):
        """All expected identities present, plus extras → missing is 0."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Scenario expects t1 × baseline × test-model × rep00/01/02 (3 runs).
        # Also build 2 extra zips with a different task name (unexpected extras).
        for rep in range(3):
            record = {"task": "t1", "mode": "baseline", "model": "test-model", "repetition": rep}
            _make_zip(record, worktree, output_dir)
        for i in range(2):
            record = {
                "task": f"extra_{i}",
                "mode": "baseline",
                "model": "test-model",
                "repetition": 0,
            }
            _make_zip(record, worktree, output_dir)

        scenario = Scenario(
            name="overflow_scenario",
            tasks=["t1"],
            modes=["baseline"],
            models=["test-model"],
            repetitions=3,
        )

        result = verify_batch(output_dir, scenario=scenario)

        assert result["authentic"] == 5
        assert result["tampered"] == []
        assert result["missing"] == 0  # all expected identities are present


class TestVerifyBatchIdentity:
    """Identity-based missing detection: reports WHICH runs are absent, not just a count."""

    def test_specific_missing_rep_is_named(self, tmp_path):
        """Provide rep00 but not rep01; verify_batch names the missing identity."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Only rep00 present
        record_rep0 = {"task": "mytask", "mode": "baseline", "model": "m", "repetition": 0}
        _make_zip(record_rep0, worktree, output_dir)

        scenario = Scenario(
            name="id_scenario",
            tasks=["mytask"],
            modes=["baseline"],
            models=["m"],
            repetitions=2,
        )

        result = verify_batch(output_dir, scenario=scenario)

        missing_ids = result["missing_ids"]
        assert isinstance(missing_ids, list)
        # Exactly one missing: rep01
        assert len(missing_ids) == 1
        missing = missing_ids[0]
        assert missing["task"] == "mytask"
        assert missing["mode"] == "baseline"
        assert missing["model"] == "m"
        assert missing["repetition"] == 1

    def test_full_set_present_no_missing_ids(self, tmp_path):
        """When all expected reps are present, missing_ids is empty."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        for rep in range(2):
            record = {"task": "mytask", "mode": "baseline", "model": "m", "repetition": rep}
            _make_zip(record, worktree, output_dir)

        scenario = Scenario(
            name="full_scenario",
            tasks=["mytask"],
            modes=["baseline"],
            models=["m"],
            repetitions=2,
        )

        result = verify_batch(output_dir, scenario=scenario)

        assert result["missing_ids"] == []
        assert result["missing"] == 0

    def test_unexpected_extras_reported(self, tmp_path):
        """Files present in dir but not in expected set appear in unexpected_ids."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Scenario expects only task_a; we also build task_b
        record_a = {"task": "task_a", "mode": "baseline", "model": "m", "repetition": 0}
        record_b = {"task": "task_b", "mode": "baseline", "model": "m", "repetition": 0}
        _make_zip(record_a, worktree, output_dir)
        _make_zip(record_b, worktree, output_dir)

        scenario = Scenario(
            name="extra_scenario",
            tasks=["task_a"],
            modes=["baseline"],
            models=["m"],
            repetitions=1,
        )

        result = verify_batch(output_dir, scenario=scenario)

        unexpected = result["unexpected_ids"]
        assert isinstance(unexpected, list)
        assert len(unexpected) == 1
        assert unexpected[0]["task"] == "task_b"

    def test_missing_ids_empty_when_no_scenario(self, tmp_path):
        """Without a scenario, missing_ids and unexpected_ids are absent or empty lists."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        _make_zip(record, worktree, output_dir)

        result = verify_batch(output_dir)

        # No scenario → identity fields default to empty
        assert result.get("missing_ids", []) == []
        assert result.get("unexpected_ids", []) == []
