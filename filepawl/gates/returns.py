"""Returns gate: a function's dict-literal returns share one key set (design.md §6.8).

A caller handed dicts of different shapes must probe them with `.get` or
`in`, and cannot tell a missing key from a bug.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import block_bodies
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.returns.exempt]"

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)

_Shape = frozenset[str]
# (qualified name, shapes of its dict-literal returns in source order) per
# function, outermost first.
_Found = list[tuple[str, list[_Shape]]]


def _shape(node: ast.Return) -> _Shape | None:
    """Return the key set of a returned dict literal, or None when it has none.

    A literal with a `**` spread (a None key) or a key that is not a string
    constant has no knowable shape.
    """
    value = node.value
    if not isinstance(value, ast.Dict):
        return None
    keys = [
        k.value
        for k in value.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    ]
    return frozenset(keys) if len(keys) == len(value.keys) else None


def _walk(
    body: list[ast.stmt], prefix: str, found: _Found, shapes: list[_Shape]
) -> None:
    """Add the shapes a list of statements returns to `shapes`, recording functions."""
    for node in body:
        if isinstance(node, _FUNCS):
            _record(node, prefix, found)
        elif isinstance(node, ast.ClassDef):
            _walk(node.body, f"{prefix}{node.name}.", found, [])
        elif isinstance(node, ast.Return):
            shapes += [shape for shape in [_shape(node)] if shape is not None]
        else:
            for inner in block_bodies(node):
                _walk(inner, prefix, found, shapes)


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Append a function's returned shapes to `found`, outermost first."""
    name = f"{prefix}{node.name}"
    shapes: list[_Shape] = []
    found.append((name, shapes))
    _walk(node.body, f"{name}.", found, shapes)


def returned_shapes(module: ast.Module) -> _Found:
    """Return (qualified name, returned shapes) for every function in a module."""
    found: _Found = []
    _walk(module.body, "", found, [])
    return found


def _distinct(shapes: list[_Shape]) -> list[_Shape]:
    """Return each shape once, in order of first appearance."""
    return list(dict.fromkeys(shapes))


def _spell(shape: _Shape) -> str:
    return "{" + ", ".join(sorted(shape)) + "}"


@dataclass
class ReturnsGate:
    """Refuses functions whose dict-literal returns carry different key sets."""

    name: str = "returns"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        exempt = policy.returns.exempt
        findings: list[Finding] = []
        measured: dict[str, _Found] = {}
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # has no shape to judge.
                continue
            measured[path] = returned_shapes(module)
            for func, shapes in measured[path]:
                distinct = _distinct(shapes)
                if len(distinct) < 2 or f"{path}::{func}" in exempt:
                    continue
                spelled = "; ".join(_spell(shape) for shape in distinct)
                message = (
                    f"returns dicts of {len(distinct)} shapes ({spelled})"
                    " — return one shape"
                )
                findings.append(Finding(f"{path}::{func}", message))
        findings += self._stale(measured, policy)
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.returns.include
        return [
            path
            for path in tree.files
            if not tree.is_test(path) and any(glob_match(g, path) for g in include)
        ]

    def _stale(self, measured: dict[str, _Found], policy: Policy) -> list[Finding]:
        findings = []
        for key in sorted(policy.returns.exempt):
            path, _, func = key.partition("::")
            named = [shapes for name, shapes in measured.get(path, []) if name == func]
            if path not in measured:
                message = "names no file"
            elif not named:
                message = "names no function"
            elif all(len(_distinct(shapes)) < 2 for shapes in named):
                message = "returns one shape, so it needs no exemption"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
