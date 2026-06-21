"""Test opt-in signing of .copeca artifacts (F-C2 real tamper-evidence).

When build_artifact is given a private key, it writes a detached Ed25519
signature over the content_hash as `manifest.sig` inside the zip. Without a key,
the artifact is byte-for-byte the same as before — signing is strictly opt-in.
"""

import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from copeca.results.artifact import MANIFEST_SIG_NAME, build_artifact
from copeca.results.signing import generate_keypair, verify_signature


class TestUnsignedArtifactUnchanged:
    def test_no_sign_key_means_no_signature_file(self, tmp_path):
        """Without sign_key, the zip contains no manifest.sig (behavior unchanged)."""
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
        assert MANIFEST_SIG_NAME not in names
        assert "manifest.json" in names


class TestSignedArtifact:
    def test_sign_key_adds_detached_signature_file(self, tmp_path):
        """With sign_key, the zip carries manifest.sig alongside manifest.json."""
        private_key, _public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert MANIFEST_SIG_NAME in names
            sig_bytes = zf.read(MANIFEST_SIG_NAME)
            manifest_raw = zf.read("manifest.json")

        import json

        content_hash = json.loads(manifest_raw)["content_hash"]
        assert verify_signature(content_hash, sig_bytes, _public_key) is True

    def test_signature_is_over_the_content_hash(self, tmp_path):
        """The stored signature verifies for the content_hash and no other value."""
        private_key, public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        import json

        with zipfile.ZipFile(zip_path, "r") as zf:
            sig_bytes = zf.read(MANIFEST_SIG_NAME)
            content_hash = json.loads(zf.read("manifest.json"))["content_hash"]

        assert verify_signature(content_hash, sig_bytes, public_key) is True
        assert verify_signature("0" * 64, sig_bytes, public_key) is False

    def test_signed_artifact_signature_not_covered_by_content_hash(self, tmp_path):
        """manifest.sig is detached: it is NOT one of the files content_hash covers.

        (Otherwise the hash would depend on the signature, which depends on the
        hash — a circular definition. The signature stands outside the manifest.)
        """
        private_key, _public_key = generate_keypair()
        record = {"task": "t", "mode": "baseline", "model": "m"}
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir, sign_key=private_key)

        import json

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        assert MANIFEST_SIG_NAME not in manifest["files"]


class TestKeypairType:
    def test_generate_keypair_returns_public_key(self):
        """generate_keypair yields a usable Ed25519 public key for verification."""
        _private_key, public_key = generate_keypair()
        assert isinstance(public_key, Ed25519PublicKey)
