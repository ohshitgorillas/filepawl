"""Mover discovery: built-ins plus `filepawl.movers` entry points (§8).

`git` is not a registry name: a language block with no `mover` gets
`GitMover`, which is the default rather than something selectable by
name, so the registry holds exactly the names `mover =` may carry.
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from filepawl.errors import ConfigError

if TYPE_CHECKING:
    from filepawl.movers.base import Mover

_ENTRY_POINT_GROUP = "filepawl.movers"

# (mover name, module to import lazily, class name in that module).
_BUILTIN_MOVERS: tuple[tuple[str, str, str], ...] = (
    ("rope", "filepawl.movers.rope_mover", "RopeMover"),
    ("command", "filepawl.movers.command", "CommandMover"),
)

_MOVER_ATTRS = ("move", "find_stale_refs")


def discover_movers() -> dict[str, type[Mover]]:
    """Every selectable mover class by name.

    An entry point that fails to load, or whose object is not a mover, is
    a configuration error (exit 2): a broken plugin is not silently
    dropped, because the language block naming it would then fall back to
    `git mv` and quietly stop rewriting imports.
    """
    movers: dict[str, type[Mover]] = {}

    for name, module_path, class_name in _BUILTIN_MOVERS:
        module = importlib.import_module(module_path)
        movers[name] = getattr(module, class_name)

    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            loaded = ep.load()
        except Exception as exc:
            raise ConfigError(
                f"entry point {ep.name!r} in group {_ENTRY_POINT_GROUP!r} "
                f"failed to load: {exc}"
            ) from exc

        missing = [attr for attr in _MOVER_ATTRS if not hasattr(loaded, attr)]
        if missing:
            raise ConfigError(
                f"entry point {ep.name!r} in group {_ENTRY_POINT_GROUP!r} "
                f"is not a valid mover (missing {', '.join(missing)})"
            )
        movers[ep.name] = loaded

    return movers
