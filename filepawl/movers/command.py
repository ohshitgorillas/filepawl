"""The `command` escape-hatch backend (docs/design.md §4, §8)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from filepawl.errors import FilepawlError
from filepawl.movers.base import BaseMover, relative_to_root


class CommandMover(BaseMover):
    """Render `mover_command` with `{old}` and `{new}` and run it via the shell.

    `{old}` and `{new}` are substituted as paths relative to the
    repository root, because the command runs with `cwd=root` and §4's
    example template (`npx jscodeshift ... --old {old} --new {new} src/`)
    reads as repository-relative.
    """

    def __init__(self, template: str) -> None:
        self.template = template

    def move(self, old: Path, new: Path, root: Path) -> list[Path]:
        command = self.template.format(
            old=relative_to_root(old, root), new=relative_to_root(new, root)
        )
        result = subprocess.run(command, shell=True, cwd=root)
        if result.returncode != 0:
            raise FilepawlError(f"mover command exited {result.returncode}: {command}")
        return [old, new]
