"""Test single-artifact verification — content_hash integrity check."""

import json
import zipfile
from pathlib import Path

import pytest

from copeca.results.artifact import build_artifact
from copeca.results.verification import verify_artifact


def _make_zip(record: dict, worktree: Path, output_dir: Path) -> Path:
    """Helper to build a valid .copeca zip."""
    return build_artifact(record, worktree, output_dir)


class TestVerifySingle:
    def test_verify_authentic_zip_returns_valid(self, tmp_path):
        """An authentic .copeca zip must verify as valid."""
        record = {"task": "auth_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = _make_zip(record, worktree, output_dir)
        valid, message = verify_artifact(zip_path)

        assert valid is True
        assert "valid" in message.lower() or "authentic" in message.lower()

    def test_verify_tampered_zip_returns_invalid(self, tmp_path):
        """Modifying result.json inside the zip must cause verification failure."""
        record = {"task": "tamper_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = _make_zip(record, worktree, output_dir)

        # Tamper: modify result.json inside the zip
        tampered_path = output_dir / "tampered.copeca.zip"
        with (
            zipfile.ZipFile(zip_path, "r") as zin,
            zipfile.ZipFile(  # noqa: SIM117
                tampered_path, "w"
            ) as zout,
        ):
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "result.json":
                    data = b'{"tampered": true}'
                zout.writestr(item, data)

        valid, message = verify_artifact(tampered_path)

        assert valid is False
        assert "tampered" in message.lower() or "hash" in message.lower()

    def test_verify_corrupted_manifest_returns_invalid(self, tmp_path):
        """Corrupting the content_hash in manifest.json must cause verification failure."""
        record = {"task": "corrupt_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = _make_zip(record, worktree, output_dir)

        # Tamper: change content_hash in manifest.json
        tampered_path = output_dir / "corrupt.copeca.zip"
        with (
            zipfile.ZipFile(zip_path, "r") as zin,
            zipfile.ZipFile(  # noqa: SIM117
                tampered_path, "w"
            ) as zout,
        ):
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(data)
                    manifest["content_hash"] = "0" * 64
                    data = json.dumps(manifest).encode("utf-8")
                zout.writestr(item, data)

        valid, message = verify_artifact(tampered_path)

        assert valid is False

    def test_verify_nonexistent_file_raises(self, tmp_path):
        """Verifying a file that does not exist raises FileNotFoundError."""
        nonexistent = tmp_path / "nonexistent.copeca.zip"
        with pytest.raises(FileNotFoundError):
            verify_artifact(nonexistent)

    def test_verify_non_zip_file_raises(self, tmp_path):
        """Verifying a file that is not a valid zip raises an error."""
        not_a_zip = tmp_path / "not_a_zip.copeca.zip"
        not_a_zip.write_text("this is not a zip file")

        valid, message = verify_artifact(not_a_zip)
        assert valid is False

    def test_verify_zip_with_content_hash_missing_from_manifest(self, tmp_path):
        """Remove content_hash key from manifest → verify returns False with 'missing'."""
        record = {"task": "noch_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = _make_zip(record, worktree, output_dir)

        # Re-create zip with content_hash removed from manifest
        tampered_path = output_dir / "no_chash.copeca.zip"
        with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(tampered_path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(data)
                    del manifest["content_hash"]
                    data = json.dumps(manifest).encode("utf-8")
                zout.writestr(item, data)

        valid, message = verify_artifact(tampered_path)

        assert valid is False
        assert "missing" in message.lower()

    def test_verify_zip_with_file_declared_but_missing(self, tmp_path):
        """Add manifest entry for nonexistent file → verify returns False, mentions file."""
        record = {"task": "phantom_test", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = _make_zip(record, worktree, output_dir)

        # Re-create zip with an extra file entry in manifest that does not exist
        tampered_path = output_dir / "phantom.copeca.zip"
        with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(tampered_path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(data)
                    manifest["files"]["missing_file.txt"] = "a" * 64
                    # Must recompute content_hash since files changed — corrupt it
                    # so we hit the per-file check
                    data = json.dumps(manifest).encode("utf-8")
                zout.writestr(item, data)

        valid, message = verify_artifact(tampered_path)

        assert valid is False
        assert "declared in manifest but missing" in message.lower()

    def test_verify_empty_zip(self, tmp_path):
        """A completely empty zip file → verify returns False (no manifest)."""
        empty_zip = tmp_path / "empty.copeca.zip"
        with zipfile.ZipFile(empty_zip, "w"):
            pass  # Create a zip with no entries

        valid, message = verify_artifact(empty_zip)

        assert valid is False
