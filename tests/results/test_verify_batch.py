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
        """With scenario providing expected count, missing is computed (expected - actual)."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create 2 zips, but scenario says 3 tasks * 1 mode * 1 model * 2 reps = 6 expected
        for i in range(2):
            record = {"task": f"task_{i}", "mode": "baseline", "model": "test"}
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
        assert result["missing"] == 4  # 6 expected - 2 actual = 4 missing

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
        """When there are more zips than expected, missing is 0 (not negative)."""
        from copeca.config.models import Scenario

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create 5 zips, but scenario says only 3 expected
        for i in range(5):
            record = {"task": f"task_{i}", "mode": "baseline", "model": "test"}
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
        assert result["missing"] == 0  # clamped to 0, not -2
