"""Handlers gate: no sentinel values from exception handlers (design.md §6.10).

A `return` inside an `except`, or a name bound there that a later return
reads, turns the exception into a value the caller must know to test for,
and drops the exception's type and traceback.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import block_bodies
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.handlers.exempt]"

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_TRIES = (ast.Try, ast.TryStar)

_ASSIGNS = (ast.Assign, ast.AnnAssign, ast.AugAssign)


@dataclass
class _Function:
    """What the handlers gate reads from one function's own statements."""

    # (line, is a value return, sits in a handler, names the value reads).
    returns: list[tuple[int, bool, bool, frozenset[str]]] = field(default_factory=list)
    # (line, name) per name a handler assignment binds.
    bound: list[tuple[int, str]] = field(default_factory=list)


# (qualified name, what it holds) per function, outermost first.
_Found = list[tuple[str, _Function]]


def _reads(node: ast.expr | None) -> frozenset[str]:
    """Return every name an expression loads."""
    if node is None:
        return frozenset()
    return frozenset(
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    )


def _binds(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[str]:
    """Return the plain names an assignment statement binds."""
    if isinstance(node, ast.AnnAssign) and node.value is None:
        return []
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [
        n.id
        for target in targets
        for n in ast.walk(target)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    ]


def _walk(
    body: list[ast.stmt],
    prefix: str,
    found: _Found,
    func: _Function,
    in_handler: bool,
) -> None:
    """Add what a list of statements returns and binds to `func`, recording defs."""
    for node in body:
        if isinstance(node, _FUNCS):
            _record(node, prefix, found)
        elif isinstance(node, ast.ClassDef):
            _walk(node.body, f"{prefix}{node.name}.", found, _Function(), False)
        elif isinstance(node, ast.Return):
            reads = _reads(node.value)
            func.returns.append(
                (node.lineno, node.value is not None, in_handler, reads)
            )
        elif isinstance(node, _ASSIGNS) and in_handler:
            func.bound += [(node.lineno, name) for name in _binds(node)]
        elif isinstance(node, _TRIES):
            for inner in (node.body, node.orelse, node.finalbody):
                _walk(inner, prefix, found, func, in_handler)
            for handler in node.handlers:
                _walk(handler.body, prefix, found, func, True)
        else:
            for inner in block_bodies(node):
                _walk(inner, prefix, found, func, in_handler)


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Append a function's returns and handler bindings to `found`, outermost first."""
    name = f"{prefix}{node.name}"
    func = _Function()
    found.append((name, func))
    _walk(node.body, f"{name}.", found, func, False)


def function_returns(module: ast.Module) -> _Found:
    """Return (qualified name, returns and handler bindings) for every function."""
    found: _Found = []
    _walk(module.body, "", found, _Function(), False)
    return found


def _failing(func: _Function) -> list[int]:
    """Return the lines where a handler hands the caller a value.

    A handler return fails when it returns a value, or when the function
    returns one elsewhere. A handler assignment fails when a value return
    reads the name it binds.
    """
    valued = any(value for _, value, _, _ in func.returns)
    returned = frozenset().union(*(reads for *_, reads in func.returns))
    lines = {
        line
        for line, value, in_handler, _ in func.returns
        if in_handler and (value or valued)
    }
    lines |= {line for line, name in func.bound if name in returned}
    return sorted(lines)


@dataclass
class HandlersGate:
    """Refuses functions that hand the caller a value from an exception handler."""

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
            for func, held in measured[path]:
                lines = _failing(held)
                if not lines or f"{path}::{func}" in exempt:
                    continue
                where = "line" if len(lines) == 1 else "lines"
                spelled = ", ".join(str(line) for line in lines)
                message = (
                    "hands the caller a value from an except handler"
                    f" at {where} {spelled}"
                    " — let it propagate, raise a narrower one, or handle it"
                    " so nothing returned stands for the failure"
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
            named = [held for name, held in measured.get(path, []) if name == func]
            if path not in measured:
                message = "names no file"
            elif not named:
                message = "names no function"
            elif not any(_failing(held) for held in named):
                message = (
                    "hands the caller no value from a handler, so it needs no exemption"
                )
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
