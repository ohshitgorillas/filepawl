"""Mover protocol and the grep every backend shares (docs/design.md §8).

`Mover.move` performs the move and reports the files it changed;
`find_stale_refs` reports `path:line: text` hits for references a move
cannot rewrite. The CLI greps for two needles (the dotted module path and
the old relative path as a literal); a backend's own `find_stale_refs`
greps the dotted path only, which is what the protocol names.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol


class Mover(Protocol):
    """A per-language move backend."""

    def move(self, old: Path, new: Path, root: Path) -> list[Path]: ...

    def find_stale_refs(self, old_dotted: str, root: Path) -> list[str]: ...


def relative_to_root(path: Path, root: Path) -> str:
    """`path` as a posix path relative to `root`, or unchanged if outside it."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def grep_refs(root: Path, files: Iterable[str], needles: Sequence[str]) -> list[str]:
    """Report `path:line: text` for every line under `root` holding a needle.

    Files are visited in the order given, so a caller passing a sorted
    tree gets sorted output. A file that cannot be decoded as UTF-8 is
    skipped: filepawl measures UTF-8 text (§6.1) and a binary blob cannot
    carry a Python import.
    """
    hits: list[str] = []
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(needle in line for needle in needles):
                hits.append(f"{rel}:{number}: {line.strip()}")
    return hits


class BaseMover:
    """Shared `find_stale_refs` for the built-in backends.

    It is a concrete base rather than part of the Protocol so that a
    third-party mover can implement the two methods without importing
    filepawl.
    """

    def find_stale_refs(self, old_dotted: str, root: Path) -> list[str]:
        from filepawl.config import load_policy
        from filepawl.tree import build_tree

        tree = build_tree(root, load_policy(root), None)
        return grep_refs(root, tree.files, [old_dotted])
