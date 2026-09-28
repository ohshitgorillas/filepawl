"""Claims gate: a test makes one claim (design.md §6.22).

A narrowing guard lets a type checker narrow a value for the claim that
follows and is not counted; a packed tuple assertion is one claim.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.gates.suite.testgate import TestGate, TestNode, own_nodes

_SUBJECTS = (ast.Name, ast.Attribute, ast.Subscript)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _guarded(test: ast.expr) -> ast.expr | None:
    """Return what a guard-shaped assert test narrows, or None."""
    subject: ast.expr | None = None
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.IsNot)
    ):
        left, right = test.left, test.comparators[0]
        subject = left if _is_none(right) else right if _is_none(left) else None
    elif (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and not test.keywords
    ):
        subject = test.args[0]
    return subject if isinstance(subject, _SUBJECTS) else None


def _read_after(nodes: list[ast.AST], guard: ast.Assert, spelling: str) -> bool:
    """Return whether an expression spelled `spelling` is read after `guard`."""
    return any(
        isinstance(node, _SUBJECTS)
        and isinstance(node.ctx, ast.Load)
        and node.lineno > (guard.end_lineno or guard.lineno)
        and ast.unparse(node) == spelling
        for node in nodes
    )


def claims(test: TestNode) -> int:
    """Return how many claims a test makes: its own asserts less its guards."""
    nodes = own_nodes(test)
    count = 0
    for node in reversed(nodes):
        if not isinstance(node, ast.Assert):
            continue
        subject = _guarded(node.test)
        if count and subject is not None:
            if _read_after(nodes, node, ast.unparse(subject)):
                continue
        count += 1
    return count


@dataclass
class ClaimsGate(TestGate):
    """Fail a test that makes more than one claim."""

    name: str = "claims"
    message: str = (
        "makes more than one claim — one claim per test; split it, or pack one"
        " contrast into a tuple assertion"
    )
    clean: str = "makes one claim, so it needs no exemption"

    def fails(self, test: TestNode) -> bool:
        return claims(test) > 1
