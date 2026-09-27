"""Reach gate: no module imports another module's private name (design.md §6.21).

A split cut along no seam leaves each half reaching into the other's
private names; the import is where that shows.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.gates.suite.common import own_names
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.reach.exempt]"
_FIX = " — make it public where it lives, or move it to its one user"


@dataclass(frozen=True)
class Reach:
    """One private name a `from` import takes from own code."""

    name: str
    source: str
    line: int


def dotted(path: str) -> str:
    """Return the module a tree path imports as, `src/` and `__init__` dropped."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_private(name: str) -> bool:
    is_dunder = name.startswith("__") and name.endswith("__")
    return name.startswith("_") and not is_dunder


def _source(path: str, node: ast.ImportFrom) -> str | None:
    """Return the absolute module a `from` import reads, or None past the top."""
    if not node.level:
        return node.module
    parts = dotted(path).split(".") if dotted(path) else []
    is_package = PurePosixPath(path).name == "__init__.py"
    package = parts if is_package else parts[:-1]
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return None
    base = package[:keep] + (node.module.split(".") if node.module else [])
    return ".".join(base) or None


def reaches(
    path: str, module: ast.Module, own: frozenset[str], modules: frozenset[str]
) -> list[Reach]:
    """Return every private name a module imports from own code, in line order.

    A relative import is always own code. A private name that is itself a
    module in the tree is a module, not a reach.
    """
    found: list[Reach] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _source(path, node)
        if source is None or (not node.level and source.split(".")[0] not in own):
            continue
        found += [
            Reach(alias.name, source, node.lineno)
            for alias in node.names
            if _is_private(alias.name) and f"{source}.{alias.name}" not in modules
        ]
    return sorted(found, key=lambda reach: reach.line)


def _message(sites: list[Reach]) -> str:
    lines = [str(site.line) for site in sites]
    where = f"line {lines[0]}" if len(lines) == 1 else f"lines {', '.join(lines)}"
    return f"imports private {sites[0].name} from {sites[0].source} at {where}{_FIX}"


@dataclass
class ReachGate:
    """Refuses a module that imports a private name from another own module."""

    name: str = "reach"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        own = own_names(tree, policy)
        modules = frozenset(dotted(p) for p in tree.files if p.endswith(".py"))
        measured: dict[str, dict[str, list[Reach]]] = {}
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # imports nothing it can be judged on.
                continue
            by_name: dict[str, list[Reach]] = {}
            for site in reaches(path, module, own, modules):
                by_name.setdefault(site.name, []).append(site)
            measured[path] = by_name
        findings = [
            Finding(f"{path}::{name}", _message(sites))
            for path, by_name in measured.items()
            for name, sites in by_name.items()
            if f"{path}::{name}" not in policy.reach.exempt
        ]
        return sorted(findings + self._stale(measured, policy))

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.reach.include
        return [
            path
            for path in tree.files
            if path.endswith(".py")
            and not tree.is_test(path)
            and any(glob_match(g, path) for g in include)
        ]

    def _stale(
        self, measured: dict[str, dict[str, list[Reach]]], policy: Policy
    ) -> list[Finding]:
        findings = []
        for key in sorted(policy.reach.exempt):
            path, _, name = key.partition("::")
            if path not in measured:
                message = "names no file"
            elif name not in measured[path]:
                message = "imports no such private name, so it needs no exemption"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
