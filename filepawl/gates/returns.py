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
_EMPTY_CONSTANTS = (None, "", b"")
_EMPTY_CALLS = frozenset({"list", "dict", "tuple", "set", "frozenset", "str"})


@dataclass(frozen=True)
class _Literal:
    """A returned dict literal: its key set, and the keys it maps to an empty value."""

    shape: _Shape
    empty: _Shape


# (qualified name, its dict-literal returns in source order) per function,
# outermost first.
_Found = list[tuple[str, list[_Literal]]]


def _is_empty(node: ast.expr) -> bool:
    """Return whether a value is None, an empty string, display or constructor."""
    if isinstance(node, ast.Constant):
        return node.value in _EMPTY_CONSTANTS and not isinstance(node.value, bool)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        bare = not node.args and not node.keywords
        return bare and node.func.id in _EMPTY_CALLS
    return False


def _literal(node: ast.Return) -> _Literal | None:
    """Return a returned dict literal's keys, or None when it has no knowable shape.

    A literal with a `**` spread (a None key) or a key that is not a string
    constant has no knowable shape.
    """
    value = node.value
    if not isinstance(value, ast.Dict):
        return None
    pairs = [
        (k.value, v)
        for k, v in zip(value.keys, value.values)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    ]
    if len(pairs) != len(value.keys):
        return None
    empty = frozenset(key for key, v in pairs if _is_empty(v))
    return _Literal(frozenset(key for key, _ in pairs), empty)


def _walk(
    body: list[ast.stmt], prefix: str, found: _Found, shapes: list[_Literal]
) -> None:
    """Add the shapes a list of statements returns to `shapes`, recording functions."""
    for node in body:
        if isinstance(node, _FUNCS):
            _record(node, prefix, found)
        elif isinstance(node, ast.ClassDef):
            _walk(node.body, f"{prefix}{node.name}.", found, [])
        elif isinstance(node, ast.Return):
            shapes += [shape for shape in [_literal(node)] if shape is not None]
        else:
            for inner in block_bodies(node):
                _walk(inner, prefix, found, shapes)


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Append a function's returned shapes to `found`, outermost first."""
    name = f"{prefix}{node.name}"
    shapes: list[_Literal] = []
    found.append((name, shapes))
    _walk(node.body, f"{name}.", found, shapes)


def returned_shapes(module: ast.Module) -> _Found:
    """Return (qualified name, returned shapes) for every function in a module."""
    found: _Found = []
    _walk(module.body, "", found, [])
    return found


def _distinct(literals: list[_Literal]) -> list[_Shape]:
    """Return each shape once, in order of first appearance."""
    return list(dict.fromkeys(literal.shape for literal in literals))


def _padded(literals: list[_Literal]) -> _Shape:
    """Return the keys some returns map to an empty value and others do not."""
    if len(_distinct(literals)) != 1:
        return frozenset()
    empty = [literal.empty for literal in literals]
    return frozenset.union(*empty) - frozenset.intersection(*empty)


def _spell(shape: _Shape) -> str:
    return "{" + ", ".join(sorted(shape)) + "}"


def _message(literals: list[_Literal]) -> str | None:
    """Return the finding a function's returns earn, or None when they pass."""
    distinct = _distinct(literals)
    if len(distinct) > 1:
        spelled = "; ".join(_spell(shape) for shape in distinct)
        return f"returns dicts of {len(distinct)} shapes ({spelled}) — return one shape"
    padded = _padded(literals)
    if padded:
        return (
            f"pads {_spell(padded)} with an empty value on some returns"
            " — a padded key is a second shape; return a named type"
        )
    return None


def failing_names(module: ast.Module) -> frozenset[str]:
    """Return the qualified name of every function the gate fails in a module."""
    return frozenset(
        name for name, literals in returned_shapes(module) if _message(literals)
    )


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
            for func, literals in measured[path]:
                message = _message(literals)
                if message is None or f"{path}::{func}" in exempt:
                    continue
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
            elif not any(_message(literals) for literals in named):
                message = "returns one unpadded shape, so it needs no exemption"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
