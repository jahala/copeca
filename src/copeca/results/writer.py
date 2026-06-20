"""JSONL writer — append a single result record to a results file.

Architecture: adapter. Filesystem I/O for result persistence.
"""

import json
from pathlib import Path
from typing import Any


def append_jsonl(record: dict[str, Any], path: Path) -> None:
    """Append a single JSONL record to a results file.

    Args:
        record: The JSON-serializable result record.
        path: Path to the results .jsonl file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
