""".copeca zip builder — hash-chained manifest for artifact integrity.

Architecture: adapter. Filesystem I/O for artifact packaging.
Never imports from orchestration/.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


COLLECTABLE_FILES = ("task.yaml", "stdout.txt", "stderr.txt")
COLLECTABLE_PREFIXES = ("task",)
COLLECTABLE_SUFFIXES = (".yaml",)


def build_artifact(record: dict[str, Any], worktree: Path, output_dir: Path) -> Path:
    """Build a .copeca zip with hash-chained manifest.

    Files in zip: result.json, manifest.json, task.yaml (if present),
    stdout.txt/stderr.txt (if present in worktree).

    manifest.json contains: per-file SHA-256 hashes, content_hash (SHA-256 of
    sorted per-file hashes concatenated), copeca_version, repo_commit, timestamp.

    Args:
        record: The JSONL result record.
        worktree: Path to the worktree directory (may contain extra files).
        output_dir: Directory where the .copeca zip is written.

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
    content_hash = hashlib.sha256(
        "".join(sorted_hashes).encode("utf-8")
    ).hexdigest()

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

    # Write the zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in file_contents.items():
            zf.writestr(fname, data)
        zf.writestr("manifest.json", manifest_bytes)

    return zip_path


def _safe_filename(s: str) -> str:
    """Replace characters that are problematic in filenames."""
    for ch in "/\\:*?\"<>| ":
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
