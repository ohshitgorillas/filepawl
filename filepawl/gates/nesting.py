"""Nesting gate: no function nests blocks past a depth limit (design.md §6.7).

Cyclomatic complexity counts branches, not indentation, so a deeply nested
but branch-cheap function passes ruff `C901` and is still unreadable.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.nesting.exempt]"

_BLOCKS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)

# (qualified name, deepest nesting) per function, outermost first.
_Found = list[tuple[str, int]]


def _is_elif(node: ast.If) -> bool:
    """Report whether an `if`'s `else` branch is really an `elif`.

    The parser represents both as an `If` inside `orelse`; only the column
    tells them apart, an `elif` starting where its `if` does.
    """
    orelse = node.orelse
    return (
        len(orelse) == 1
        and isinstance(orelse[0], ast.If)
        and orelse[0].col_offset == node.col_offset
    )


def _if_depth(node: ast.If, depth: int, prefix: str, found: _Found) -> int:
    """Return the deepest nesting inside an `if`, its `elif` arms sharing its level."""
    deepest = _walk(node.body, depth + 1, prefix, found)
    arm = node.orelse[0] if _is_elif(node) else None
    if isinstance(arm, ast.If):
        return max(deepest, _if_depth(arm, depth, prefix, found))
    return max(deepest, _walk(node.orelse, depth + 1, prefix, found))


def block_bodies(node: ast.stmt) -> list[list[ast.stmt]]:
    """Return every statement list a block hands its body to."""
    bodies = [getattr(node, name, []) for name in ("body", "orelse", "finalbody")]
    bodies += [handler.body for handler in getattr(node, "handlers", [])]
    bodies += [case.body for case in getattr(node, "cases", [])]
    return bodies


def _statement_depth(node: ast.stmt, depth: int, prefix: str, found: _Found) -> int:
    """Return the deepest nesting one statement reaches, recording its functions."""
    if isinstance(node, _FUNCS):
        _record(node, prefix, found)
        return depth
    if isinstance(node, ast.ClassDef):
        return _walk(node.body, depth, f"{prefix}{node.name}.", found)
    if isinstance(node, ast.If):
        return _if_depth(node, depth, prefix, found)
    if isinstance(node, _BLOCKS):
        bodies = block_bodies(node)
        return max(_walk(body, depth + 1, prefix, found) for body in bodies)
    return depth


def _walk(body: list[ast.stmt], depth: int, prefix: str, found: _Found) -> int:
    """Return the deepest nesting a list of statements reaches, from `depth`."""
    return max(
        [depth, *(_statement_depth(node, depth, prefix, found) for node in body)]
    )


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Append a function's measurement to `found`, outermost first."""
    name = f"{prefix}{node.name}"
    slot = len(found)
    found.append((name, 0))
    found[slot] = (name, _walk(node.body, 0, f"{name}.", found))


def depths(module: ast.Module) -> _Found:
    """Return (qualified name, deepest nesting) for every function in a module."""
    found: _Found = []
    _walk(module.body, 0, "", found)
    return found


@dataclass
class NestingGate:
    """Refuses functions that nest blocks deeper than `max_depth`."""

    name: str = "nesting"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        nesting = policy.nesting
        limit = nesting.max_depth
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
            measured[path] = depths(module)
            findings += [
                Finding(
                    f"{path}::{func}",
                    f"nests {depth} deep (max {limit}) — flatten the function",
                )
                for func, depth in measured[path]
                if depth > limit and f"{path}::{func}" not in nesting.exempt
            ]
        findings += self._stale(measured, policy)
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.nesting.include
        return [
            path for path in tree.files if any(glob_match(g, path) for g in include)
        ]

    def _stale(self, measured: dict[str, _Found], policy: Policy) -> list[Finding]:
        limit = policy.nesting.max_depth
        findings = []
        for key in sorted(policy.nesting.exempt):
            path, _, func = key.partition("::")
            named = [depth for name, depth in measured.get(path, []) if name == func]
            if path not in measured:
                message = "names no file"
            elif not named:
                message = "names no function"
            elif max(named) <= limit:
                message = f"nests {max(named)} deep, within the limit of {limit}"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
