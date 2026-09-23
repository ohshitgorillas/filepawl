"""Barrels gate: re-export modules and trivial forwarders (design.md §6.6).

A split moves code; it does not leave a shell behind pointing at where the
code went. Ported from the `no-barrels` script HQPTuner, Trivia Judge and
Gauntlet each carry; the rules are not widened.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_REEXPORT = "imports and defines nothing — a re-export module is not a split"
_FORWARDER = "returns a call on its own arguments — move the callers, not the method"

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _named_all(node: ast.stmt) -> bool:
    """Report whether a statement assigns `__all__`, a re-export's own manifest."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        targets = []
    return any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets)


def _defines_something(module: ast.Module) -> bool:
    """Report whether a module defines a function, a class or a constant."""
    for node in module.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return True
        if isinstance(node, ast.Assign | ast.AnnAssign) and not _named_all(node):
            return True
    return False


def _imports_anything(module: ast.Module) -> bool:
    return any(isinstance(node, ast.Import | ast.ImportFrom) for node in module.body)


def is_reexport(path: str, module: ast.Module) -> bool:
    """Report whether a file is imports and nothing else; `__init__.py` never is."""
    if path.rsplit("/", 1)[-1] == "__init__.py":
        return False
    return _imports_anything(module) and not _defines_something(module)


def _sole_return(func: _Function) -> ast.expr | None:
    """Return the expression a function does nothing but return, else None.

    A leading docstring is allowed; its presence says nothing about what the
    function does.
    """
    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    return body[0].value


def _called(expr: ast.expr) -> ast.Call | None:
    """Return the call an expression is, seeing through a single await."""
    if isinstance(expr, ast.Await):
        expr = expr.value
    return expr if isinstance(expr, ast.Call) else None


def _chain_root(expr: ast.expr) -> str | None:
    """Return the name an attribute chain is rooted at, or None."""
    while isinstance(expr, ast.Attribute):
        expr = expr.value
    return expr.id if isinstance(expr, ast.Name) else None


def _passes_through(func: _Function, call: ast.Call) -> bool:
    """Report whether a call hands on exactly the function's own parameters.

    The first parameter is dropped when the chain is rooted at it: in
    `def f(self, x): return self._other.f(x)`, `self` is spent on the chain.
    """
    if call.keywords or any(isinstance(arg, ast.Starred) for arg in call.args):
        return False
    expected = [arg.arg for arg in func.args.posonlyargs + func.args.args]
    if expected and _chain_root(call.func) == expected[0]:
        expected = expected[1:]
    passed = [arg.id for arg in call.args if isinstance(arg, ast.Name)]
    return len(passed) == len(call.args) and passed == expected


def is_forwarder(func: _Function) -> bool:
    """Report whether a function is a bare pass-through to somewhere else."""
    returned = _sole_return(func)
    call = _called(returned) if returned is not None else None
    if (
        call is None
        or not isinstance(call.func, ast.Attribute)
        or _chain_root(call.func) is None
    ):
        return False
    return _passes_through(func, call)


def forwarders(path: str, module: ast.Module) -> list[str]:
    """Return the `path::function` key of every forwarder in a module."""
    return [
        f"{path}::{node.name}"
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and is_forwarder(node)
    ]


@dataclass
class BarrelsGate:
    """Refuses files shortened by leaving a shell behind."""

    name: str = "barrels"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        barrels = policy.barrels
        findings: list[Finding] = []
        parsed: dict[str, ast.Module] = {}
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # has no shape to judge.
                continue
            parsed[path] = module
            if is_reexport(path, module) and path not in barrels.module_exempt:
                findings.append(Finding(path, _REEXPORT))
            if any(glob_match(g, path) for g in barrels.forwarders):
                findings += [
                    Finding(key, _FORWARDER)
                    for key in forwarders(path, module)
                    if key not in barrels.forwarder_exempt
                ]
        findings += self._stale(parsed, policy)
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.barrels.include
        return [
            path
            for path in tree.files
            if not tree.is_test(path) and any(glob_match(g, path) for g in include)
        ]

    def _stale(self, parsed: dict[str, ast.Module], policy: Policy) -> list[Finding]:
        findings = []
        for path in sorted(policy.barrels.module_exempt):
            module = parsed.get(path)
            if module is None:
                message = "names no file"
            elif not is_reexport(path, module):
                message = "the module defines something, so it needs no exemption"
            else:
                continue
            where = f"[tool.filepawl.barrels.module_exempt] {path!r}"
            findings.append(Finding(_POLICY_FILE, f"{where}: {message}"))
        for key in sorted(policy.barrels.forwarder_exempt):
            module = parsed.get(key.partition("::")[0])
            if module is None:
                message = "names no file"
            elif key not in forwarders(key.partition("::")[0], module):
                message = "matches no forwarder"
            else:
                continue
            where = f"[tool.filepawl.barrels.forwarder_exempt] {key!r}"
            findings.append(Finding(_POLICY_FILE, f"{where}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
