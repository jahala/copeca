"""Test the .copeca zip artifact builder — hash-chained manifest integrity."""

import hashlib
import json
import zipfile

from copeca.results.artifact import build_artifact


class TestBuildArtifact:
    def test_builds_zip_with_result_and_manifest(self, tmp_path):
        """A .copeca zip must contain result.json and manifest.json at minimum."""
        record = {
            "task": "test_task",
            "mode": "baseline",
            "model": "test-model",
        }
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "result.json" in names
            assert "manifest.json" in names

    def test_manifest_contains_per_file_hashes(self, tmp_path):
        """manifest.json must contain SHA-256 hashes for every file in the zip."""
        record = {
            "task": "hash_test",
            "mode": "baseline",
            "model": "test-model",
        }
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "stdout.txt").write_text("hello world")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        assert "files" in manifest
        assert "result.json" in manifest["files"]
        assert "stdout.txt" in manifest["files"]
        # Verify the hash is correct for stdout.txt
        expected_hash = hashlib.sha256(b"hello world").hexdigest()
        assert manifest["files"]["stdout.txt"] == expected_hash

    def test_content_hash_is_sha256_of_sorted_hashes(self, tmp_path):
        """content_hash must be SHA-256 of sorted per-file hashes concatenated."""
        record = {
            "task": "content_hash_test",
            "mode": "baseline",
            "model": "test-model",
        }
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "stdout.txt").write_text("aaa")
        (worktree / "stderr.txt").write_text("bbb")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        # Compute expected content_hash manually
        hash_stdout = hashlib.sha256(b"aaa").hexdigest()
        hash_stderr = hashlib.sha256(b"bbb").hexdigest()
        result_bytes = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
        hash_result = hashlib.sha256(result_bytes).hexdigest()

        # Build file_hashes as the code does, then sort by filename (key)
        file_hashes_dict = {
            "result.json": hash_result,
            "stderr.txt": hash_stderr,
            "stdout.txt": hash_stdout,
        }
        sorted_hashes = [file_hashes_dict[k] for k in sorted(file_hashes_dict)]
        expected_content_hash = hashlib.sha256(
            "".join(sorted_hashes).encode("utf-8")
        ).hexdigest()

        assert manifest["content_hash"] == expected_content_hash

    def test_empty_record_builds_minimal_zip(self, tmp_path):
        """An empty record dict should still produce a valid minimal .copeca zip."""
        record: dict = {}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        assert zip_path.exists()
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "result.json" in names
            assert "manifest.json" in names
            manifest = json.loads(zf.read("manifest.json"))
            assert "content_hash" in manifest
            assert "files" in manifest

    def test_zip_filename_includes_task_mode_model(self, tmp_path):
        """The zip filename must encode task, mode, and model for traceability."""
        record = {
            "task": "find_matcher",
            "mode": "experimental",
            "model": "claude-sonnet-4-6",
        }
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        name = zip_path.name
        assert "find_matcher" in name
        assert "experimental" in name
        assert "claude-sonnet-4-6" in name

    def test_manifest_contains_metadata_fields(self, tmp_path):
        """manifest.json must include copeca_version, repo_commit, and timestamp."""
        record = {"task": "meta_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        assert "copeca_version" in manifest
        assert "repo_commit" in manifest
        assert "timestamp" in manifest
        assert manifest["copeca_version"] == "0.1.0"

    def test_task_yaml_included_when_present(self, tmp_path):
        """If task.yaml exists in worktree, it must be included in the zip."""
        record = {"task": "yaml_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "task.yaml").write_text("name: test_task\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            assert "task.yaml" in zf.namelist()
