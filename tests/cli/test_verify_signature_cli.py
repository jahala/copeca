"""Test `copeca verify --pubkey` (F-C2 tamper-evidence at the CLI).

Covers the operator-facing surface: a signed artifact verified with the matching
public key reports valid and exits 0; a forged-and-recomputed artifact (the
attack the old self-hash check could not catch) exits non-zero; an unsigned
artifact is clearly reported as unsigned / corruption-only and never as
tamper-proof.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from copeca.results.artifact import MANIFEST_SIG_NAME, build_artifact
from copeca.results.signing import generate_keypair, serialize_public_key_pem


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the installed copeca CLI entry point."""
    return subprocess.run(
        [sys.executable, "-m", "copeca", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )


def _write_pubkey(path: Path, public_key) -> None:
    path.write_bytes(serialize_public_key_pem(public_key))


class TestVerifyPubkey:
    def test_signed_artifact_verifies_with_matching_pubkey(self, tmp_path: Path) -> None:
        """A signed artifact + matching --pubkey exits 0 and reports a valid signature."""
        private_key, public_key = generate_keypair()
        worktree = tmp_path / "wt"
        worktree.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        artifact = build_artifact(record, worktree, out, sign_key=private_key)

        pub_path = tmp_path / "pub.pem"
        _write_pubkey(pub_path, public_key)

        result = copeca("verify", str(artifact), "--pubkey", str(pub_path))

        combined = (result.stdout + result.stderr).lower()
        assert result.returncode == 0, f"Expected exit 0.\n{result.stdout}\n{result.stderr}"
        assert "signed" in combined
        assert "valid" in combined

    def test_forged_artifact_fails_with_pubkey(self, tmp_path: Path) -> None:
        """A forged-and-recomputed artifact exits non-zero under --pubkey."""
        private_key, public_key = generate_keypair()
        worktree = tmp_path / "wt"
        worktree.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        record = {"task": "t", "mode": "baseline", "model": "m", "correct": False}
        artifact = build_artifact(record, worktree, out, sign_key=private_key)

        # Attacker edits result.json and recomputes a consistent manifest, keeping
        # the stale signature.
        with zipfile.ZipFile(artifact, "r") as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
            base_manifest = json.loads(members["manifest.json"])

        import hashlib

        members["result.json"] = json.dumps(
            {**record, "correct": True}, indent=2, sort_keys=True
        ).encode("utf-8")
        file_hashes = {
            n: hashlib.sha256(d).hexdigest()
            for n, d in members.items()
            if n not in ("manifest.json", MANIFEST_SIG_NAME)
        }
        sorted_hashes = [file_hashes[k] for k in sorted(file_hashes)]
        base_manifest["files"] = file_hashes
        base_manifest["content_hash"] = hashlib.sha256(
            "".join(sorted_hashes).encode("utf-8")
        ).hexdigest()
        members["manifest.json"] = json.dumps(base_manifest, indent=2, sort_keys=True).encode(
            "utf-8"
        )

        forged = out / "forged.copeca.zip"
        with (
            zipfile.ZipFile(artifact, "r") as zin,
            zipfile.ZipFile(  # noqa: SIM117
                forged, "w"
            ) as zout,
        ):
            for item in zin.infolist():
                zout.writestr(item, members[item.filename])

        pub_path = tmp_path / "pub.pem"
        _write_pubkey(pub_path, public_key)

        result = copeca("verify", str(forged), "--pubkey", str(pub_path))

        assert result.returncode != 0, (
            f"Forged artifact must fail signature verify.\n{result.stdout}\n{result.stderr}"
        )

    def test_wrong_pubkey_fails(self, tmp_path: Path) -> None:
        """Verifying with an unrelated pubkey exits non-zero."""
        private_key, _public_key = generate_keypair()
        _other_priv, other_public = generate_keypair()
        worktree = tmp_path / "wt"
        worktree.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        artifact = build_artifact(record, worktree, out, sign_key=private_key)

        pub_path = tmp_path / "other_pub.pem"
        _write_pubkey(pub_path, other_public)

        result = copeca("verify", str(artifact), "--pubkey", str(pub_path))

        assert result.returncode != 0, f"Wrong pubkey must fail.\n{result.stdout}\n{result.stderr}"

    def test_unsigned_artifact_with_pubkey_reports_unsigned_not_tamperproof(
        self, tmp_path: Path
    ) -> None:
        """An unsigned artifact + --pubkey is clearly reported as unsigned and
        exits non-zero (a pubkey was requested but no signature exists)."""
        worktree = tmp_path / "wt"
        worktree.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        artifact = build_artifact(record, worktree, out)  # unsigned

        _private_key, public_key = generate_keypair()
        pub_path = tmp_path / "pub.pem"
        _write_pubkey(pub_path, public_key)

        result = copeca("verify", str(artifact), "--pubkey", str(pub_path))

        combined = (result.stdout + result.stderr).lower()
        assert result.returncode != 0
        assert "unsigned" in combined or "no signature" in combined
        assert "tamper-proof" not in combined

    def test_unsigned_artifact_without_pubkey_still_corruption_checks(self, tmp_path: Path) -> None:
        """No --pubkey: the original corruption-only verify path is unchanged (exit 0)."""
        worktree = tmp_path / "wt"
        worktree.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        record = {"task": "t", "mode": "baseline", "model": "m", "repetition": 0}
        artifact = build_artifact(record, worktree, out)

        result = copeca("verify", str(artifact))

        assert result.returncode == 0, (
            f"Unsigned artifact without --pubkey must still verify corruption.\n"
            f"{result.stdout}\n{result.stderr}"
        )


class TestRunSignKey:
    """`copeca run --sign-key` wiring: flag exposure, guard, and key validation.

    The end-to-end "build a signed artifact" path is exercised by the artifact
    and verification unit tests (build_artifact(sign_key=...) is the load-bearing
    call). These CLI tests cover the run-command branches in cli.py that load and
    validate the key before any run is attempted — fully offline.
    """

    def test_run_help_advertises_sign_key(self) -> None:
        """run --help must document --sign-key (operator discoverability)."""
        result = copeca("run", "--help")
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
        assert "--sign-key" in clean, f"run --help must advertise --sign-key.\n{result.stdout}"

    def test_sign_key_requires_artifacts(self, tmp_path: Path) -> None:
        """--sign-key without --artifacts fails fast with a clear error (exit 2)."""
        from copeca.results.signing import generate_keypair, serialize_private_key_pem

        private_key, _public_key = generate_keypair()
        priv_path = tmp_path / "priv.pem"
        priv_path.write_bytes(serialize_private_key_pem(private_key))

        task_path = tmp_path / "task.yaml"
        task_path.write_text("name: noop\n")

        result = copeca("run", "--task", str(task_path), "--sign-key", str(priv_path))

        assert result.returncode == 2, (
            f"--sign-key without --artifacts must exit 2.\n{result.stdout}\n{result.stderr}"
        )
        assert "--artifacts" in (result.stdout + result.stderr)

    def test_invalid_sign_key_is_rejected(self, tmp_path: Path) -> None:
        """A non-PEM --sign-key file is rejected before any run (exit 2)."""
        bad_key = tmp_path / "bad.pem"
        bad_key.write_text("not a real private key")

        task_path = tmp_path / "task.yaml"
        task_path.write_text("name: noop\n")

        result = copeca("run", "--task", str(task_path), "--artifacts", "--sign-key", str(bad_key))

        assert result.returncode == 2, (
            f"Invalid signing key must exit 2.\n{result.stdout}\n{result.stderr}"
        )
        assert "key" in (result.stdout + result.stderr).lower()
