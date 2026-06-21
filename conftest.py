"""Root conftest.py — add project root to sys.path so tests can import from scripts/."""

import sys
from pathlib import Path

# Make `scripts/` importable as a top-level package (no __init__.py needed).
sys.path.insert(0, str(Path(__file__).parent))
