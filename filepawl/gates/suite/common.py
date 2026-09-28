"""Rules the test-suite gates share (design.md §6.12): own code, imports,
units, and the site-gate engine."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import Tree, glob_match


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
    packages: frozenset[str] = frozenset()

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
    return Imports(own=frozenset(bound_own), origins=origins, packages=own)


_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
MODULE_UNIT = "<module>"


def units(module: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """Yield every node below a module with the unit it belongs to: the
    qualified name of its innermost function, or `<module>`."""
    yield from _units_below(module, MODULE_UNIT, "")


def _units_below(
    node: ast.AST, unit: str, prefix: str
) -> Iterator[tuple[str, ast.AST]]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCS):
            name = f"{prefix}{child.name}"
            yield name, child
            yield from _units_below(child, name, f"{name}.")
        elif isinstance(child, ast.ClassDef):
            yield unit, child
            yield from _units_below(child, unit, f"{prefix}{child.name}.")
        else:
            yield unit, child
            yield from _units_below(child, unit, prefix)


def parsed(
    tree: Tree, include: tuple[str, ...]
) -> Iterator[tuple[str, ast.Module, str]]:
    """Yield each checked file that parses, with its module and text."""
    for path in checked_files(tree, include):
        try:
            text = (tree.root / path).read_text(encoding="utf-8")
            module = ast.parse(text, filename=path)
        except (SyntaxError, UnicodeDecodeError):
            # Syntax is the compiler's gate; a file that does not parse has
            # nothing to judge.
            continue
        yield path, module, text


def checked_files(tree: Tree, include: tuple[str, ...]) -> list[str]:
    """Return the test paths a test-suite gate reads."""
    return [
        path
        for path in tree.files
        if tree.is_test(path) and any(glob_match(g, path) for g in include)
    ]


def stale_entry(
    name: str, key: str, measured: dict[str, dict[str, bool]], messages: Stale
) -> Finding | None:
    """Audit one exemption against what the run measured: `measured[path]`
    maps each unit or test in the file to whether it fails."""
    path, _, unit = key.partition("::")
    if path not in measured:
        message = "names no file"
    elif unit not in measured[path]:
        message = messages.missing
    elif not measured[path][unit]:
        message = messages.clean
    else:
        return None
    return Finding(_POLICY_FILE, f"[tool.filepawl.{name}.exempt] {key!r}: {message}")


_POLICY_FILE = "pyproject.toml"


@dataclass(frozen=True)
class Stale:
    """The audit messages for an exemption that excuses nothing."""

    missing: str
    clean: str


def _lines(sites: list[int]) -> str:
    if len(sites) == 1:
        return f"at line {sites[0]}"
    return "at lines " + ", ".join(str(n) for n in sites)


class SiteGate:
    """A gate that reports sites under their unit (design.md §6.12)."""

    name: str
    fix: str
    clean: str

    def sites(
        self, module: ast.Module, imports: Imports, policy: Policy
    ) -> list[tuple[str, int, str]]:
        """Return (unit, line, detail) for every site in a module."""
        raise NotImplementedError

    def text_sites(self, module: ast.Module, text: str) -> list[tuple[str, int, str]]:
        """Return (unit, line, detail) for every site in a module's comments."""
        return []

    def describe(self, details: list[str]) -> str:
        """Return what a unit with these site details does."""
        raise NotImplementedError

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        table = getattr(policy.suite, self.name)
        own = own_names(tree, policy)
        findings: list[Finding] = []
        measured: dict[str, dict[str, bool]] = {}
        for path, module, text in parsed(tree, table.include):
            judged = measured.setdefault(path, {MODULE_UNIT: False})
            judged.update(
                (unit, False)
                for unit, node in units(module)
                if isinstance(node, _FUNCS)
            )
            grouped: dict[str, list[tuple[int, str]]] = {}
            found_sites = self.sites(module, read_imports(module, own), policy)
            for unit, line, detail in found_sites + self.text_sites(module, text):
                grouped.setdefault(unit, []).append((line, detail))
            for unit, found in grouped.items():
                judged[unit] = True
                if f"{path}::{unit}" in table.exempt:
                    continue
                found.sort()
                details = list(dict.fromkeys(detail for _, detail in found))
                lines = sorted({line for line, _ in found})
                message = f"{self.describe(details)} {_lines(lines)} — {self.fix}"
                findings.append(Finding(f"{path}::{unit}", message))
        messages = Stale(missing="names no function", clean=self.clean)
        for key in sorted(table.exempt):
            stale = stale_entry(self.name, key, measured, messages)
            if stale is not None:
                findings.append(stale)
        return sorted(findings)

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
