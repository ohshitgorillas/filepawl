"""The default backend: plain `git mv` (docs/design.md §8).

A language block with no `mover` gets this: the file moves, the index
follows, and nothing is rewritten — the stale-reference grep the CLI runs
afterwards is the whole of the import story for such a block.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from filepawl.errors import FilepawlError
from filepawl.movers.base import BaseMover, relative_to_root


class GitMover(BaseMover):
    def move(self, old: Path, new: Path, root: Path) -> list[Path]:
        result = subprocess.run(
            ["git", "mv", relative_to_root(old, root), relative_to_root(new, root)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise FilepawlError(f"git mv failed: {detail}")
        return [old, new]
