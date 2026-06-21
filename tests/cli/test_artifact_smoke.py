"""End-to-end smoke test: create, verify, tamper, reverify a .copeca artifact."""

import json
import zipfile

from copeca.results.artifact import build_artifact
from copeca.results.verification import verify_artifact


class TestArtifactSmoke:
    """Create -> verify -> tamper -> reverify cycle."""

    def test_create_verify_tamper_reverify(self, tmp_path):
        """Full lifecycle: build zip, verify passes, tamper, verify fails with filename."""
        # Phase 1: Create a valid .copeca zip
        record = {
            "task": "smoke_test",
            "mode": "baseline",
            "model": "claude-haiku-4-5",
            "correct": True,
        }
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "stdout.txt").write_text("agent output here")
        (worktree / "stderr.txt").write_text("error log here")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)
        assert zip_path.exists()

        # Phase 2: Verify it passes
        valid, message = verify_artifact(zip_path)
        assert valid is True, f"Expected valid, got: {message}"

        # Phase 3: Modify one byte in result.json inside the zip
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
                    # Modify one byte
                    data = bytearray(data)
                    data[0] = (data[0] + 1) % 256
                    data = bytes(data)
                zout.writestr(item, data)

        # Phase 4: Verify it fails with the tampered file named
        valid2, message2 = verify_artifact(tampered_path)
        assert valid2 is False, "Tampered zip should not verify as valid"
        assert "result.json" in message2.lower(), (
            f"Message should mention the tampered file, got: {message2}"
        )

    def test_reverify_after_manifest_tamper(self, tmp_path):
        """Tampering content_hash in manifest also must be detected."""
        record = {"task": "manifest_tamper", "mode": "baseline", "model": "test"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        # Tamper manifest.json content_hash
        tampered_path = output_dir / "manifest_tampered.copeca.zip"
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
                    manifest["content_hash"] = "a" * 64
                    data = json.dumps(manifest, indent=2).encode("utf-8")
                zout.writestr(item, data)

        valid, message = verify_artifact(tampered_path)
        assert valid is False, f"Manifest tampered zip should fail, got: {message}"
