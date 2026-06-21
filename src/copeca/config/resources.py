"""Bundled-data resolver — anchors on the installed package, not the source tree.

Architecture: domain layer boundary helper. ``data_path`` is a pure function of
its arguments: it returns the filesystem path of a file shipped inside the
``copeca`` package's ``data/`` tree, resolving identically in a source checkout
and in a pip-installed wheel (``importlib.resources``, never ``__file__``
parent-traversal).
"""

from importlib.resources import files
from pathlib import Path


def data_path(*parts: str) -> Path:
    """Resolve a bundled data file/dir; works in source checkout AND installed wheel."""
    return Path(str(files("copeca").joinpath("data", *parts)))
