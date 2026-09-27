"""`filepawl mv OLD NEW` (docs/design.md §8).

Kept out of `cli.py` so that module stays under the watch line. The
sequence is §8's: resolve the language block, run its mover, grep the
tree for references the mover could not rewrite, move any allowance
entry, exit 0 whenever the move ran.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from filepawl.cli import relative_paths
from filepawl.config import LanguagePolicy, Policy, load_policy
from filepawl.errors import ConfigError
from filepawl.movers import registry
from filepawl.movers.base import Mover, grep_refs
from filepawl.movers.git_mover import GitMover
from filepawl.state import Entry, State, load_state, write_state
from filepawl.tree import build_tree, find_root, glob_match


def run_mv(old_arg: str, new_arg: str, stream: TextIO | None = None) -> int:
    out = sys.stdout if stream is None else stream
    root = find_root(Path.cwd())
    policy = load_policy(root)
    old_rel, new_rel = relative_paths(root, [old_arg, new_arg])

    language, language_policy = _language_of(policy, old_rel)
    mover = _mover_for(language, language_policy)

    # NEW's parent is not created here: whether a missing destination is
    # made or refused belongs to the backend. `git mv` and the `command`
    # template create it; rope requires an existing package and says so.
    mover.move(root / old_rel, root / new_rel, root)

    _report_stale(root, policy, old_rel, out)
    _move_allowance(root, old_rel, new_rel)
    return 0


def _language_of(policy: Policy, old_rel: str) -> tuple[str, LanguagePolicy]:
    """The first language block whose `include` matches OLD.

    Blocks are tried in `pyproject.toml` order, so a path matched by two
    blocks belongs to the earlier one.
    """
    for name, language_policy in policy.languages.items():
        if any(glob_match(pattern, old_rel) for pattern in language_policy.include):
            return name, language_policy
    raise ConfigError(f"{old_rel}: no language block's `include` matches it")


def _mover_for(language: str, language_policy: LanguagePolicy) -> Mover:
    name = language_policy.mover
    if name is None:
        return GitMover()

    movers = registry.discover_movers()
    factory = movers.get(name)
    if factory is None:
        raise ConfigError(f"unknown mover {name!r} in [tool.filepawl.{language}]")

    if name == "command":
        template = language_policy.mover_command
        if template is None:
            raise ConfigError(
                f'[tool.filepawl.{language}] sets mover = "command" '
                f"without `mover_command`"
            )
        return factory(template)  # type: ignore[call-arg]
    return factory()


def _dotted(old_rel: str) -> str:
    """OLD as a dotted module path: `/` becomes `.` and a `.py` suffix goes.

    A non-Python path keeps its extension, so the dotted needle for
    `src/a/b.js` is `src.a.b.js` — harmless, since the literal-path
    needle is what finds references in such a tree.
    """
    stem = old_rel[: -len(".py")] if old_rel.endswith(".py") else old_rel
    return stem.replace("/", ".")


def _report_stale(root: Path, policy: Policy, old_rel: str, out: TextIO) -> None:
    """Print `path:line: text` for every leftover reference, then the count.

    The tree is rescanned after the move, so a backend that leaves the
    destination untracked (`command`, `rope`) has its new path excluded
    and its old path already gone. Nothing is edited: §8 step 5 prints
    and counts so an agent can act on the list.
    """
    tree = build_tree(root, policy, None)
    needles = [_dotted(old_rel)]
    if old_rel not in needles:
        needles.append(old_rel)
    hits = grep_refs(root, tree.files, needles)
    for hit in hits:
        print(hit, file=out)
    print(f"{len(hits)} stale references", file=out)


def _move_allowance(root: Path, old_rel: str, new_rel: str) -> None:
    """Rewrite an allowance entry under NEW, `lines` and `reason` verbatim.

    The length is not remeasured: §8 says the entry moves, and a move
    does not change a file's length. A shrink or a growth is the length
    gate's business on the next `check`.
    """
    state = load_state(root)
    entry = state.allowance.get(old_rel)
    if entry is None:
        return
    allowance = dict(state.allowance)
    del allowance[old_rel]
    allowance[new_rel] = Entry(lines=entry.lines, reason=entry.reason)
    write_state(root, State(version=state.version, allowance=allowance))
