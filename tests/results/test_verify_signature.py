"""Test signature-aware verification (F-C2: real tamper-evidence).

The audit proved that the integrity manifest alone does NOT stop deliberate
tampering: an attacker edits a file, recomputes the per-file hashes and the
content_hash, rewrites manifest.json, and `verify` passes. A detached Ed25519
signature over the content_hash closes that hole — the attacker cannot produce a
valid signature without the private key.

`verify_signed_artifact(path, public_key)` returns a SignatureReport:
  - signed:   does the artifact carry a manifest.sig?
  - valid:    does the signature verify over the recomputed content_hash?
  - corruption_ok / message: the underlying integrity-manifest result.

An UNSIGNED artifact reports signed=False and never claims tamper-proof.
"""

import json
import zipfile
from pathlib import Path

from copeca.results.artifact import MANIFEST_SIG_NAME, build_artifact
from copeca.results.signing import generate_keypair
from copeca.results.verification import verify_signed_artifact


def _rewrite_zip(src: Path, dst: Path, edits: dict[str, bytes]) -> None:
    """Copy a zip member-by-member, replacing the named members' bytes."""
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w") as zout:  # noqa: SIM117
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in edits:
                data = edits[item.filename]
            zout.writestr(item, data)


def _recompute_manifest_for_files(file_bytes: dict[str, bytes], base_manifest: dict) -> dict:
    """Recompute per-file hashes + content_hash exactly as build_artifact does.

    This is what a knowledgeable attacker would run after editing files: it makes
    the integrity manifest internally consistent again. The signature must still
    catch it.
    """
    import hashlib

    file_hashes = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in file_bytes.items()
        if name not in ("manifest.json", MANIFEST_SIG_NAME)
    }
    sorted_hashes = [file_hashes[k] for k in sorted(file_hashes)]
    content_hash = hashlib.sha256("".join(sorted_hashes).encode("utf-8")).hexdigest()
    manifest = dict(base_manifest)
    manifest["files"] = file_hashes
    manifest["content_hash"] = content_hash
    return manifest


class TestSignedVerificationHappyPath:
    def test_signed_artifact_with_matching_pubkey_is_valid(self, tmp_path):
        """A signed artifact verifies as signed=True, valid=True under its pubkey."""
        private_key, public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "stdout.txt").write_text("agent output")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        report = verify_signed_artifact(zip_path, public_key=public_key)

        assert report.signed is True
        assert report.valid is True
        assert report.corruption_ok is True


class TestForgedArtifactIsRejected:
    def test_forged_artifact_is_rejected(self, tmp_path):
        """THE forge that previously passed: edit a file, recompute the manifest
        like an attacker, and the signature verification must now FAIL.

        Before F-C2, `verify` only recomputed content_hash from the manifest and
        passed. With a detached signature the attacker — lacking the private key —
        cannot re-sign the new content_hash, so verification fails.
        """
        private_key, public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m", "correct": False}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        # Attacker rewrites result.json (correct: False -> True) and recomputes a
        # fully self-consistent manifest. They keep the original (now-stale)
        # signature because they cannot forge a new one.
        with zipfile.ZipFile(zip_path, "r") as zf:
            original = {name: zf.read(name) for name in zf.namelist()}
            base_manifest = json.loads(original["manifest.json"])

        forged_result = json.dumps(
            {**record, "correct": True}, indent=2, sort_keys=True
        ).encode("utf-8")
        new_files = dict(original)
        new_files["result.json"] = forged_result
        new_manifest = _recompute_manifest_for_files(new_files, base_manifest)
        new_files["manifest.json"] = json.dumps(
            new_manifest, indent=2, sort_keys=True
        ).encode("utf-8")

        forged_path = output_dir / "FORGED.copeca.zip"
        _rewrite_zip(zip_path, forged_path, new_files)

        # Sanity: the integrity manifest alone is internally consistent (this is
        # exactly why the old self-hash check passed on the forgery).
        manifest_only = verify_signed_artifact(forged_path, public_key=None)
        assert manifest_only.corruption_ok is True

        # But the signature does NOT verify over the new content_hash.
        report = verify_signed_artifact(forged_path, public_key=public_key)
        assert report.signed is True
        assert report.valid is False, "Forged-and-recomputed artifact must fail signature check"

    def test_stripped_signature_is_not_silently_accepted(self, tmp_path):
        """If an attacker deletes manifest.sig, a pubkey-checking verify must not
        report valid=True — the artifact is then unsigned, not authentic."""
        private_key, public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        stripped = output_dir / "stripped.copeca.zip"
        with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(  # noqa: SIM117
            stripped, "w"
        ) as zout:
            for item in zin.infolist():
                if item.filename == MANIFEST_SIG_NAME:
                    continue
                zout.writestr(item, zin.read(item.filename))

        report = verify_signed_artifact(stripped, public_key=public_key)
        assert report.signed is False
        assert report.valid is False


class TestWrongKeyRejected:
    def test_wrong_public_key_fails(self, tmp_path):
        """A signed artifact verified with an unrelated pubkey reports valid=False."""
        private_key, _public_key = generate_keypair()
        _other_priv, other_public = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        report = verify_signed_artifact(zip_path, public_key=other_public)
        assert report.signed is True
        assert report.valid is False


class TestUnsignedArtifactNeverClaimsTamperProof:
    def test_unsigned_artifact_reports_unsigned_and_corruption_only(self, tmp_path):
        """An unsigned artifact: signed=False, valid=False, corruption_ok=True.

        valid=False here means "no verified signature", NOT "corrupt". The report
        must make clear it is corruption-detection only — never tamper-proof.
        """
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)  # no sign_key

        # No pubkey supplied: still does corruption detection.
        report_no_key = verify_signed_artifact(zip_path, public_key=None)
        assert report_no_key.signed is False
        assert report_no_key.valid is False
        assert report_no_key.corruption_ok is True

        # Even with a pubkey supplied, an unsigned artifact cannot be valid.
        _private_key, public_key = generate_keypair()
        report_with_key = verify_signed_artifact(zip_path, public_key=public_key)
        assert report_with_key.signed is False
        assert report_with_key.valid is False
        assert report_with_key.corruption_ok is True

    def test_unsigned_corrupted_artifact_still_detected(self, tmp_path):
        """Corruption detection still works for unsigned artifacts (naive tamper)."""
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        # Naive tamper: edit result.json without fixing the manifest.
        tampered = output_dir / "naive.copeca.zip"
        _rewrite_zip(zip_path, tampered, {"result.json": b'{"correct": true}'})

        report = verify_signed_artifact(tampered, public_key=None)
        assert report.signed is False
        assert report.corruption_ok is False
