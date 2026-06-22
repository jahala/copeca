"""Module entry point so `python -m copeca` runs the CLI.

Tests and tooling invoke the CLI via ``sys.executable -m copeca`` for a portable
entry point that does not depend on a .venv/bin path or on PATH resolution.
"""

from copeca.cli import app

if __name__ == "__main__":
    app()
