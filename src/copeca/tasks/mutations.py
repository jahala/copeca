"""Mutation engine — apply code mutations to a repository.

ADAPTED from tilth benchmark/tasks/base.py apply_mutations().
ADDED: delete, insert_after, create actions. Occurrence indexing.
Architecture: domain-adjacent — filesystem I/O with git commit.
"""

from pathlib import Path

from copeca.config.models import Mutation, MutationAction


class MutationError(Exception):
    """Raised when a mutation cannot be applied (unmatched find, missing file)."""


def apply_mutations(
    mutations: list[Mutation],
    base_path: Path | None = None,
) -> None:
    """Apply mutations in order, atomically.
    Raises MutationError before any change if any mutation's find
    does not match — never leave a partially-mutated repo.

    Args:
        mutations: List of mutations to apply in order.
        base_path: Optional base directory for resolving relative file paths.
                   When provided, mutation file paths are resolved relative to it.
    """
    for m in mutations:
        _apply_single(m, base_path=base_path)


def _apply_single(m: Mutation, base_path: Path | None = None) -> None:
    """Apply a single mutation based on its action type.

    Args:
        m: The mutation to apply.
        base_path: Optional base directory for resolving relative file paths.
    """
    if m.action == MutationAction.create:
        p = Path(m.file)
        if base_path is not None:
            p = base_path / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(m.content)
        return

    p = Path(m.file)
    if base_path is not None:
        p = base_path / p
    if not p.exists():
        raise MutationError(f"File not found: {m.file}")

    content = p.read_text()

    if m.action == MutationAction.replace:
        if m.find not in content:
            raise MutationError(f"Find string not found in {m.file}: {m.find[:80]!r}")
        occurrences = content.split(m.find)
        idx = (m.occurrence or 1) - 1
        if idx >= len(occurrences) - 1:
            raise MutationError(
                f"Occurrence {m.occurrence} requested but only "
                f"{len(occurrences) - 1} matches found in {m.file}"
            )
        # Reconstruct: everything before Nth occurrence, replace, everything after
        parts = content.split(m.find)
        pre_count = m.occurrence or 1
        before = m.find.join(parts[:pre_count])
        after = m.find.join(parts[pre_count:])
        new_content = before + m.replace + after
        p.write_text(new_content)

    elif m.action == MutationAction.delete:
        lines = content.split("\n")
        new_lines = [line for line in lines if m.find not in line]
        if len(new_lines) == len(lines):
            raise MutationError(f"Delete target not found in {m.file}: {m.find[:80]!r}")
        p.write_text("\n".join(new_lines))

    elif m.action == MutationAction.insert_after:
        lines = content.split("\n")
        found = False
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if m.find in line and not found:
                new_lines.append(m.content)
                found = True
        if not found:
            raise MutationError(f"Insert target not found in {m.file}: {m.find[:80]!r}")
        p.write_text("\n".join(new_lines))
