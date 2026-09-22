"""The `command` escape-hatch backend (docs/design.md §4, §8)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from filepawl.errors import FilepawlError
from filepawl.movers.base import BaseMover, relative_to_root


class CommandMover(BaseMover):
    """Render `mover_command` with `{old}` and `{new}` and run it via the shell.

    `{old}` and `{new}` are substituted as paths relative to the
    repository root, because the command runs with `cwd=root` and §4's
    example template (`npx jscodeshift ... --old {old} --new {new} src/`)
    reads as repository-relative. They are substituted shell-quoted: the
    template goes to a shell, so a path carrying a space, a `$` or a
    quote must reach the command as one word and unexpanded.
    """

    def __init__(self, template: str) -> None:
        self.template = template

    def move(self, old: Path, new: Path, root: Path) -> list[Path]:
        new.parent.mkdir(parents=True, exist_ok=True)
        command = self._render(
            shlex.quote(relative_to_root(old, root)),
            shlex.quote(relative_to_root(new, root)),
        )
        result = subprocess.run(command, shell=True, cwd=root)
        if result.returncode != 0:
            raise FilepawlError(f"mover command exited {result.returncode}: {command}")
        return [old, new]

    def _render(self, old: str, new: str) -> str:
        """Substitute the two placeholders, or name the broken template.

        `mover_command` is hand-written policy, so `{other}`, a stray
        brace or `{0}` are configuration errors (exit 2) rather than a
        traceback out of `str.format`.
        """
        try:
            return self.template.format(old=old, new=new)
        except (KeyError, IndexError, ValueError) as exc:
            raise FilepawlError(
                f"mover_command takes only {{old}} and {{new}}: "
                f"{self.template} ({exc.__class__.__name__}: {exc})"
            ) from exc
