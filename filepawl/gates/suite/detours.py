"""Detours gate: no test claims or narrows around an assert (design.md §6.23).

A helper's `raise AssertionError` or `pytest.fail` makes a claim no gate that
reads `assert` statements sees, and a `cast`, a `# type: ignore[union-attr]`
or an `x or {}` reads through an optional the test never claims present.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.suite.common import MODULE_UNIT, Imports, SiteGate, units
from filepawl.gates.suite.testgate import is_absent

_CALLS = {
    "pytest.fail": "pytest.fail",
    "typing.cast": "cast",
    "typing_extensions.cast": "cast",
}
_IGNORE = re.compile(r"type:\s*ignore(?:\[([^\]]*)\])?")
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _detail(node: ast.AST, imports: Imports) -> str | None:
    """Return the detour a node takes, or None."""
    if isinstance(node, ast.Raise) and node.exc is not None:
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(exc, ast.Name) and exc.id == "AssertionError":
            return "raise AssertionError"
    if isinstance(node, ast.Call):
        return _CALLS.get(imports.dotted(node.func) or "")
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return "or <absent>" if is_absent(node.values[-1]) else None
    return None


def _ignores(text: str) -> list[int]:
    """Return the lines of `# type: ignore` comments that silence union-attr."""
    lines: list[int] = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        match = _IGNORE.search(token.string) if token.type == tokenize.COMMENT else None
        if match is None:
            continue
        codes = match.group(1)
        if codes is None or "union-attr" in {c.strip() for c in codes.split(",")}:
            lines.append(token.start[0])
    return lines


def _unit_at(module: ast.Module, line: int) -> str:
    """Return the innermost function whose lines span `line`, or `<module>`."""
    spans = [
        (node.lineno, unit)
        for unit, node in units(module)
        if isinstance(node, _FUNCS) and node.lineno <= line <= (node.end_lineno or 0)
    ]
    return max(spans)[1] if spans else MODULE_UNIT


@dataclass
class DetoursGate(SiteGate):
    """Refuses claims and narrowing that route around an assert."""

    name: str = "detours"
    fix: str = "assert in the test: a guard for an optional, a claim for a check"
    clean: str = "routes around no assert, so it needs no exemption"

    def sites(
        self, module: ast.Module, imports: Imports, policy: Policy
    ) -> list[tuple[str, int, str]]:
        found: list[tuple[str, int, str]] = []
        for unit, node in units(module):
            detail = _detail(node, imports)
            if detail is not None:
                found.append((unit, getattr(node, "lineno", 0), detail))
        return found

    def text_sites(self, module: ast.Module, text: str) -> list[tuple[str, int, str]]:
        return [(_unit_at(module, n), n, "type: ignore") for n in _ignores(text)]

    def describe(self, details: list[str]) -> str:
        return "routes around an assert through " + ", ".join(details)
