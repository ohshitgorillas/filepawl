"""Private gate: no test reaches a private name (design.md §6.13).

A test that reads a private attribute or imports a private name pins the
layout of the code instead of its behavior.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.suite.common import Imports, SiteGate, is_own_dotted, units

_NAMED_TUPLE = frozenset({"_asdict", "_replace", "_fields", "_field_defaults", "_make"})
_ATTR_CALLS = frozenset({"getattr", "setattr", "delattr", "hasattr"})
_DOTTED_CALLS = frozenset({"patch", "setattr", "delattr"})
_RECEIVERS = frozenset({"self", "cls"})


def is_private(name: str) -> bool:
    """Return whether a name is private: a leading `_`, not a dunder, not a
    named-tuple member."""
    if not name.startswith("_") or name in _NAMED_TUPLE:
        return False
    return not (name.startswith("__") and name.endswith("__") and len(name) > 4)


def _file_own(module: ast.Module) -> frozenset[str]:
    """Return the private names the checked file defines."""
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id in _RECEIVERS
        ):
            names.add(node.attr)
    return frozenset(name for name in names if is_private(name))


def _import_detail(node: ast.AST, own: frozenset[str]) -> str | None:
    """Return the private segment or name an own-code import reaches."""
    modules: list[str] = []
    names: list[str] = []
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
        modules = [node.module]
        names = [alias.name for alias in node.names]
    for module in modules:
        if not is_own_dotted(module, own):
            continue
        for part in [*module.split("."), *names]:
            if is_private(part):
                return part
    return None


def _callee(node: ast.Call) -> tuple[str, str | None]:
    """Return a call's last name and, on a chain, the name before it."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        before = func.value
        if isinstance(before, ast.Attribute):
            return func.attr, before.attr
        if isinstance(before, ast.Name):
            return func.attr, before.id
        return func.attr, None
    return "", None


def _string(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _call_detail(node: ast.Call, own: frozenset[str]) -> str | None:
    """Return the private name a call reaches by string, or None."""
    name, before = _callee(node)
    if name in _ATTR_CALLS or (name == "object" and before == "patch"):
        attribute = _string(node, 1)
        if attribute is not None:
            return attribute
    if name in _DOTTED_CALLS:
        dotted = _string(node, 0)
        if dotted is not None and is_own_dotted(dotted, own):
            return next((part for part in dotted.split(".") if is_private(part)), None)
    return None


def _detail(node: ast.AST, mine: frozenset[str], own: frozenset[str]) -> str | None:
    """Return the private name a node reaches, or None."""
    if isinstance(node, ast.Attribute):
        receiver = node.value
        if isinstance(receiver, ast.Name) and receiver.id in _RECEIVERS:
            return None
        name: str | None = node.attr
    elif isinstance(node, ast.Call):
        name = _call_detail(node, own)
    else:
        return _import_detail(node, own)
    if name is None or not is_private(name) or name in mine:
        return None
    return name


@dataclass
class PrivateGate(SiteGate):
    """Refuses tests that reach a private attribute or import a private name."""

    name: str = "private"
    fix: str = "test through the public surface"
    clean: str = "reaches no private name, so it needs no exemption"

    def sites(
        self, module: ast.Module, imports: Imports, policy: Policy
    ) -> list[tuple[str, int, str]]:
        mine = _file_own(module)
        found = []
        for unit, node in units(module):
            detail = _detail(node, mine, imports.packages)
            if detail is not None:
                found.append((unit, getattr(node, "lineno", 0), detail))
        return found

    def describe(self, details: list[str]) -> str:
        return "reaches " + ", ".join(details)
