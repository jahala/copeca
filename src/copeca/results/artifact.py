""".copeca zip builder — integrity manifest, with opt-in detached signing.

Architecture: adapter. Filesystem I/O for artifact packaging.
Never imports from orchestration/.

The manifest (per-file SHA-256 hashes + a content_hash over them) detects
accidental corruption. It is NOT tamper-proof on its own: anyone who can rewrite
the zip can recompute it. When a private key is supplied (``sign_key``), a
detached Ed25519 signature over the content_hash is written as ``manifest.sig``;
that signature can only be produced by a private-key holder, so a tampered (and
manifest-recomputed) artifact fails signature verification (see verification.py).
Signing is strictly opt-in — without ``sign_key`` the zip is unchanged.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


COLLECTABLE_FILES = ("task.yaml", "stdout.txt", "stderr.txt")
COLLECTABLE_PREFIXES = ("task",)
COLLECTABLE_SUFFIXES = (".yaml",)

# Detached-signature member name. Held OUTSIDE the manifest's `files` map and
# excluded from content_hash on verification (the signature covers the hash, so
# the hash cannot cover the signature without becoming circular).
MANIFEST_SIG_NAME = "manifest.sig"


def build_artifact(
    record: dict[str, Any],
    worktree: Path,
    output_dir: Path,
    sign_key: Ed25519PrivateKey | None = None,
) -> Path:
    """Build a .copeca zip with an integrity manifest (and optional signature).

    Files in zip: result.json, manifest.json, task.yaml (if present),
    stdout.txt/stderr.txt (if present in worktree), and — when ``sign_key`` is
    given — ``manifest.sig`` (a detached Ed25519 signature over content_hash).

    manifest.json contains: per-file SHA-256 hashes, content_hash (SHA-256 of
    sorted per-file hashes concatenated), copeca_version, repo_commit, timestamp.

    Args:
        record: The JSONL result record.
        worktree: Path to the worktree directory (may contain extra files).
        output_dir: Directory where the .copeca zip is written.
        sign_key: Optional Ed25519 private key. When provided, the content_hash
            is signed and the detached signature is stored as ``manifest.sig``.
            When None (default), no signature is written and the zip is unchanged.

    Returns:
        Path to the created .copeca zip.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine the zip filename from record fields
    task = str(record.get("task", "unknown"))
    mode = str(record.get("mode", "unknown"))
    model = str(record.get("model", "unknown"))
    rep = int(record.get("repetition", 0))
    safe_task = _safe_filename(task)
    safe_mode = _safe_filename(mode)
    safe_model = _safe_filename(model)
    zip_name = f"{safe_task}__{safe_mode}__{safe_model}__rep{rep:02d}.copeca.zip"
    zip_path = output_dir / zip_name

    # Serialize result.json
    result_bytes = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")

    # Collect per-file hashes
    file_hashes: dict[str, str] = {}
    file_contents: dict[str, bytes] = {}

    # Always include result.json
    result_hash = hashlib.sha256(result_bytes).hexdigest()
    file_hashes["result.json"] = result_hash
    file_contents["result.json"] = result_bytes

    # Collect optional worktree files
    for fname in COLLECTABLE_FILES:
        fpath = worktree / fname
        if fpath.is_file():
            data = fpath.read_bytes()
            file_hashes[fname] = hashlib.sha256(data).hexdigest()
            file_contents[fname] = data

    # Compute content_hash: SHA-256 of sorted per-file hashes concatenated
    sorted_hashes = [file_hashes[k] for k in sorted(file_hashes)]
    content_hash = hashlib.sha256("".join(sorted_hashes).encode("utf-8")).hexdigest()

    # Determine repo_commit from worktree (if available)
    repo_commit = _repo_commit_from_worktree(worktree)

    # Build manifest
    manifest: dict[str, Any] = {
        "content_hash": content_hash,
        "files": file_hashes,
        "copeca_version": importlib.metadata.version("copeca"),
        "repo_commit": repo_commit,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    # Opt-in: a detached signature over content_hash. Computed at the edge here
    # (sign() itself is pure); only a private-key holder can produce it.
    signature: bytes | None = None
    if sign_key is not None:
        from copeca.results.signing import sign

        signature = sign(content_hash, sign_key)

    # Write the zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in file_contents.items():
            zf.writestr(fname, data)
        zf.writestr("manifest.json", manifest_bytes)
        if signature is not None:
            zf.writestr(MANIFEST_SIG_NAME, signature)

    return zip_path


def _safe_filename(s: str) -> str:
    """Replace characters that are problematic in filenames."""
    for ch in '/\\:*?"<>| ':
        s = s.replace(ch, "_")
    return s


def _repo_commit_from_worktree(worktree: Path) -> str | None:
    """Try to read the current git commit SHA from a worktree, returning None on failure."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return None
