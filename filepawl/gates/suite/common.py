"""Rules the test-suite gates share: own code and imports (design.md §6.12)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath

from filepawl.config import Policy
from filepawl.tree import Tree


def own_names(tree: Tree, policy: Policy) -> frozenset[str]:
    """Return the top-level import names of the repository's own code."""
    if policy.packages is not None:
        return frozenset(policy.packages)
    names: set[str] = set()
    for path in tree.files:
        if not path.endswith(".py") or tree.is_test(path):
            continue
        parts = PurePosixPath(path).parts
        if parts[0] == "src" and len(parts) > 1:
            parts = parts[1:]
        names.add(parts[0].removesuffix(".py") if len(parts) == 1 else parts[0])
    return frozenset(names)


def is_own_dotted(text: str, own: frozenset[str]) -> bool:
    """Return whether a dotted string's first segment is an own name."""
    return text.split(".", 1)[0] in own


def _chain(node: ast.expr) -> list[str] | None:
    """Return an attribute chain as names, root first, or None."""
    names: list[str] = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    names.append(node.id)
    return names[::-1]


@dataclass(frozen=True)
class Imports:
    """What a checked file's import statements bind."""

    own: frozenset[str]
    origins: dict[str, str]

    def dotted(self, node: ast.expr) -> str | None:
        """Return an attribute chain's dotted name, its root resolved."""
        chain = _chain(node)
        if chain is None:
            return None
        root = self.origins.get(chain[0], chain[0])
        return ".".join([root, *chain[1:]])

    def own_rooted(self, node: ast.expr) -> bool:
        """Return whether an expression is an own binding or a chain rooted at one."""
        chain = _chain(node)
        return chain is not None and chain[0] in self.own


def read_imports(module: ast.Module, own: frozenset[str]) -> Imports:
    """Collect every import in a module, whatever its scope."""
    origins: dict[str, str] = {}
    bound_own: set[str] = set()
    for node in ast.walk(module):
        pairs: list[tuple[str, str]] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is None:
                    root = alias.name.split(".", 1)[0]
                    pairs.append((root, root))
                else:
                    pairs.append((alias.asname, alias.name))
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            pairs += [
                (alias.asname or alias.name, f"{node.module}.{alias.name}")
                for alias in node.names
                if alias.name != "*"
            ]
        for name, origin in pairs:
            origins[name] = origin
            if is_own_dotted(origin, own):
                bound_own.add(name)
    return Imports(own=frozenset(bound_own), origins=origins)
