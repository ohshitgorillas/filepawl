"""Handlers gate: no sentinel returns from exception handlers (design.md §6.10).

A `return` inside an `except` turns the exception into a value the caller
must know to test for, and drops the exception's type and traceback.
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
_WHERE = "[tool.filepawl.handlers.exempt]"

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_TRIES = (ast.Try, ast.TryStar)

# (line, is a value return, sits in a handler) per return, in source order.
_Returns = list[tuple[int, bool, bool]]
# (qualified name, its returns) per function, outermost first.
_Found = list[tuple[str, _Returns]]


def _walk(
    body: list[ast.stmt],
    prefix: str,
    found: _Found,
    returns: _Returns,
    in_handler: bool,
) -> None:
    """Add the returns a list of statements makes to `returns`, recording functions."""
    for node in body:
        if isinstance(node, _FUNCS):
            _record(node, prefix, found)
        elif isinstance(node, ast.ClassDef):
            _walk(node.body, f"{prefix}{node.name}.", found, [], False)
        elif isinstance(node, ast.Return):
            returns.append((node.lineno, node.value is not None, in_handler))
        elif isinstance(node, _TRIES):
            for inner in (node.body, node.orelse, node.finalbody):
                _walk(inner, prefix, found, returns, in_handler)
            for handler in node.handlers:
                _walk(handler.body, prefix, found, returns, True)
        else:
            for inner in block_bodies(node):
                _walk(inner, prefix, found, returns, in_handler)


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Append a function's returns to `found`, outermost first."""
    name = f"{prefix}{node.name}"
    returns: _Returns = []
    found.append((name, returns))
    _walk(node.body, f"{name}.", found, returns, False)


def function_returns(module: ast.Module) -> _Found:
    """Return (qualified name, returns) for every function in a module."""
    found: _Found = []
    _walk(module.body, "", found, [], False)
    return found


def _failing(returns: _Returns) -> list[int]:
    """Return the lines of the handler returns that hand the caller a value."""
    valued = any(value for _, value, _ in returns)
    return [
        line for line, value, in_handler in returns if in_handler and (value or valued)
    ]


@dataclass
class HandlersGate:
    """Refuses functions that return a value from an exception handler."""

    name: str = "handlers"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        exempt = policy.handlers.exempt
        findings: list[Finding] = []
        measured: dict[str, _Found] = {}
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # has no handler to judge.
                continue
            measured[path] = function_returns(module)
            for func, returns in measured[path]:
                lines = _failing(returns)
                if not lines or f"{path}::{func}" in exempt:
                    continue
                where = "line" if len(lines) == 1 else "lines"
                spelled = ", ".join(str(line) for line in lines)
                message = (
                    f"returns from an except handler at {where} {spelled}"
                    " — raise instead of returning a sentinel"
                )
                findings.append(Finding(f"{path}::{func}", message))
        findings += self._stale(measured, policy)
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.handlers.include
        return [
            path
            for path in tree.files
            if not tree.is_test(path) and any(glob_match(g, path) for g in include)
        ]

    def _stale(self, measured: dict[str, _Found], policy: Policy) -> list[Finding]:
        findings = []
        for key in sorted(policy.handlers.exempt):
            path, _, func = key.partition("::")
            named = [
                returns for name, returns in measured.get(path, []) if name == func
            ]
            if path not in measured:
                message = "names no file"
            elif not named:
                message = "names no function"
            elif not any(_failing(returns) for returns in named):
                message = "returns from no handler, so it needs no exemption"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
