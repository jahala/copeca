"""Artifact verification — content_hash integrity checks for .copeca zips.

Architecture: adapter. Filesystem I/O for artifact verification.
Never imports from orchestration/.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def verify_artifact(path: Path) -> tuple[bool, str]:
    """Verify a .copeca zip's content_hash matches its manifest.

    Opens the zip, reads manifest.json, recomputes the content_hash from
    all other files in the zip, and compares. Returns (valid, message).

    Args:
        path: Path to the .copeca zip file.

    Returns:
        (valid, message) — True = authentic, False = tampered or malformed.

    Raises:
        FileNotFoundError: If the path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")

    if not path.is_file():
        return False, f"Not a file: {path}"

    # Try to open as zip
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as e:
        return False, f"Not a valid zip file: {e}"

    with zf:
        namelist = zf.namelist()

        if "manifest.json" not in namelist:
            return False, "manifest.json missing from artifact"

        # Read and parse manifest
        try:
            manifest_raw = zf.read("manifest.json")
            manifest = json.loads(manifest_raw)
        except (KeyError, json.JSONDecodeError) as e:
            return False, f"Failed to parse manifest.json: {e}"

        expected_content_hash = manifest.get("content_hash")
        if not expected_content_hash:
            return False, "content_hash missing from manifest.json"

        # Recompute hashes for all non-manifest files
        file_hashes: dict[str, str] = {}
        for name in sorted(namelist):
            if name == "manifest.json":
                continue
            try:
                data = zf.read(name)
                file_hashes[name] = hashlib.sha256(data).hexdigest()
            except Exception as e:
                return False, f"Failed to read {name}: {e}"

        if not file_hashes:
            return False, "No content files in artifact"

        # Compute content_hash from sorted per-file hashes
        sorted_hashes = [file_hashes[k] for k in sorted(file_hashes)]
        computed_content_hash = hashlib.sha256(
            "".join(sorted_hashes).encode("utf-8")
        ).hexdigest()

        if computed_content_hash != expected_content_hash:
            # Determine which file(s) are mismatched
            manifest_files = manifest.get("files", {})
            mismatches = []
            for fname, expected_h in manifest_files.items():
                if fname in file_hashes:
                    if file_hashes[fname] != expected_h:
                        mismatches.append(fname)
                else:
                    mismatches.append(f"{fname} (missing)")
            if mismatches:
                return False, f"Artifact tampered: hash mismatch in {', '.join(mismatches)}"
            return False, "Artifact tampered: content_hash mismatch"

        # Also verify per-file hashes in manifest match reality
        manifest_files = manifest.get("files", {})
        for fname, expected_h in manifest_files.items():
            if fname not in file_hashes:
                return False, f"Artifact tampered: file {fname} declared in manifest but missing"
            if file_hashes[fname] != expected_h:
                return False, f"Artifact tampered: hash mismatch for {fname}"

        return True, "Artifact valid: content_hash matches all files"


def verify_batch(
    results_dir: Path,
    scenario: Any | None = None,
) -> dict[str, object]:
    """Verify all .copeca zips in a directory.

    Args:
        results_dir: Directory containing .copeca zip files.
        scenario: Optional Scenario to compute expected run count.
                  When provided, missing = expected - actual (minimum 0).
                  When None, missing defaults to 0.

    Returns:
        {"authentic": N, "tampered": [...], "missing": N}
    """
    authentic = 0
    tampered: list[str] = []
    actual_count = 0

    if not results_dir.is_dir():
        if scenario is not None:
            expected = (
                len(scenario.tasks)
                * len(scenario.modes)
                * len(scenario.models)
                * scenario.repetitions
            )
            return {
                "authentic": 0,
                "tampered": [],
                "missing": max(expected, 0),
            }
        return {"authentic": 0, "tampered": [], "missing": 0}

    for entry in sorted(results_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix != ".zip" and not entry.name.endswith(".copeca.zip"):
            continue
        actual_count += 1
        try:
            valid, message = verify_artifact(entry)
        except FileNotFoundError:
            continue

        if valid:
            authentic += 1
        else:
            tampered.append(entry.name)

    missing = 0
    if scenario is not None:
        expected = (
            len(scenario.tasks)
            * len(scenario.modes)
            * len(scenario.models)
            * scenario.repetitions
        )
        missing = max(expected - actual_count, 0)

    return {"authentic": authentic, "tampered": tampered, "missing": missing}
