"""Artifact verification — content_hash integrity checks for .copeca zips.

Architecture: adapter. Filesystem I/O for artifact verification.
Never imports from orchestration/.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import zipfile
from pathlib import Path
from typing import Any


# Matches: {task}__{mode}__{model}__rep{NN}.copeca.zip
_ARTIFACT_RE = re.compile(
    r"^(?P<task>.+)__(?P<mode>.+)__(?P<model>.+)__rep(?P<rep>\d+)\.copeca\.zip$"
)


def _parse_artifact_identity(filename: str) -> dict[str, Any] | None:
    """Parse a .copeca zip filename into its (task, mode, model, repetition) identity.

    Returns None if the filename does not match the expected pattern.

    Pure function — no I/O.
    """
    m = _ARTIFACT_RE.match(filename)
    if not m:
        return None
    return {
        "task": m.group("task"),
        "mode": m.group("mode"),
        "model": m.group("model"),
        "repetition": int(m.group("rep")),
    }


def _expected_identities(scenario: Any) -> list[dict[str, Any]]:
    """Build the full cross-product of expected (task, mode, model, rep) identities.

    Pure function — no I/O.
    """
    return [
        {"task": task, "mode": mode, "model": model, "repetition": rep}
        for task, mode, model, rep in itertools.product(
            scenario.tasks,
            scenario.modes,
            scenario.models,
            range(scenario.repetitions),
        )
    ]


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

    When a scenario is provided, compares by IDENTITY: parses each artifact
    filename into (task, mode, model, rep) and returns the specific missing
    and unexpected run identities.

    Args:
        results_dir: Directory containing .copeca zip files.
        scenario: Optional Scenario for identity-based completeness checking.
                  When None, missing/unexpected identity fields are empty lists.

    Returns:
        {
            "authentic": N,
            "tampered": [filename, ...],
            "missing": N,               # len(missing_ids) for backward compat
            "missing_ids": [...],       # specific absent identities (with scenario)
            "unexpected_ids": [...],    # identities present but not in expected set
        }
    """
    authentic = 0
    tampered: list[str] = []
    found_ids: list[dict[str, Any]] = []

    if not results_dir.is_dir():
        if scenario is not None:
            expected_ids = _expected_identities(scenario)
            return {
                "authentic": 0,
                "tampered": [],
                "missing": len(expected_ids),
                "missing_ids": expected_ids,
                "unexpected_ids": [],
            }
        return {
            "authentic": 0,
            "tampered": [],
            "missing": 0,
            "missing_ids": [],
            "unexpected_ids": [],
        }

    for entry in sorted(results_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".copeca.zip"):
            continue
        try:
            valid, message = verify_artifact(entry)
        except FileNotFoundError:
            continue

        if valid:
            authentic += 1
        else:
            tampered.append(entry.name)

        identity = _parse_artifact_identity(entry.name)
        if identity is not None:
            found_ids.append(identity)

    if scenario is None:
        return {
            "authentic": authentic,
            "tampered": tampered,
            "missing": 0,
            "missing_ids": [],
            "unexpected_ids": [],
        }

    expected_ids = _expected_identities(scenario)
    # Use frozensets of items for O(1) membership test
    expected_set = {
        (d["task"], d["mode"], d["model"], d["repetition"]) for d in expected_ids
    }
    found_set = {
        (d["task"], d["mode"], d["model"], d["repetition"]) for d in found_ids
    }

    missing_keys = expected_set - found_set
    unexpected_keys = found_set - expected_set

    missing_ids = [
        {"task": t, "mode": mo, "model": ml, "repetition": r}
        for t, mo, ml, r in sorted(missing_keys)
    ]
    unexpected_ids = [
        {"task": t, "mode": mo, "model": ml, "repetition": r}
        for t, mo, ml, r in sorted(unexpected_keys)
    ]

    return {
        "authentic": authentic,
        "tampered": tampered,
        "missing": len(missing_ids),
        "missing_ids": missing_ids,
        "unexpected_ids": unexpected_ids,
    }
