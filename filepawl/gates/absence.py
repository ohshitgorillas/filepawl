"""Absence gate: no test that asserts only an absent value (design.md §6.11).

A test whose every assertion is that something is absent passes against
code that never ran the feature, because a feature that does nothing
produces exactly that absence.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.absence.exempt]"
_MESSAGE = (
    "asserts only an absent value — code that never ran the feature passes"
    " it too; assert it beside a case where the feature acts"
)

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
# Nodes whose contents are not the enclosing test's own statements.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_WITHS = (ast.With, ast.AsyncWith)
_CONTEXTS = frozenset({"raises", "warns", "deprecated_call"})
_EMPTY_CALLS = frozenset({"list", "dict", "set", "tuple", "frozenset", "str", "bytes"})


def _is_absent_constant(value: object) -> bool:
    """Return whether a constant is None, False, 0, 0.0, "" or b""."""
    if value is None or value is False:
        return True
    return type(value) in (int, float, str, bytes) and not value


def is_absent(node: ast.expr) -> bool:
    """Return whether an expression is an absent value as §6.11 defines it."""
    if isinstance(node, ast.Constant):
        return _is_absent_constant(node.value)
    if isinstance(node, ast.List):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.Tuple):
        return all(is_absent(elt) for elt in node.elts)
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id in _EMPTY_CALLS
            and not node.args
            and not node.keywords
        )
    return False


def is_absence_assertion(node: ast.Assert) -> bool:
    """Return whether an assert claims only that something is absent."""
    test = node.test
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], (ast.Eq, ast.Is)):
        return False
    return is_absent(test.left) or is_absent(test.comparators[0])


def _asserts_otherwise(node: ast.AST) -> bool:
    """Return whether a node is a raises/warns context or an `assert*` call."""
    if isinstance(node, _WITHS):
        return any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr in _CONTEXTS
            for item in node.items
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("assert")
    )


def _judge(node: ast.AST, asserts: list[bool]) -> bool:
    """Collect the test's own asserts; return whether it asserts something else."""
    if _asserts_otherwise(node):
        return True
    if isinstance(node, ast.Assert):
        asserts.append(is_absence_assertion(node))
    return any(
        _judge(child, asserts)
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, _SCOPES)
    )


def fails(test: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a test has asserts, all of them absence assertions, and
    asserts nothing else."""
    asserts: list[bool] = []
    for node in test.body:
        if isinstance(node, _SCOPES):
            continue
        if _judge(node, asserts):
            return False
    return bool(asserts) and all(asserts)


def _tests_in(
    module: ast.Module,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Return (qualified name, node) for every test a module defines."""
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in module.body:
        if isinstance(node, _FUNCS) and node.name.startswith("test"):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found += [
                (f"{node.name}.{method.name}", method)
                for method in node.body
                if isinstance(method, _FUNCS) and method.name.startswith("test")
            ]
    return found


@dataclass
class AbsenceGate:
    """Refuses tests whose only claim is that something is absent."""

    name: str = "absence"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        exempt = policy.absence.exempt
        findings: list[Finding] = []
        measured: dict[str, dict[str, bool]] = {}
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # has no test to judge.
                continue
            judged = measured.setdefault(path, {})
            for name, test in _tests_in(module):
                failed = fails(test)
                judged[name] = judged.get(name, False) or failed
                if failed and f"{path}::{name}" not in exempt:
                    findings.append(Finding(f"{path}::{name}", _MESSAGE))
        findings += self._stale(measured, policy)
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.absence.include
        return [
            path
            for path in tree.files
            if tree.is_test(path) and any(glob_match(g, path) for g in include)
        ]

    def _stale(
        self, measured: dict[str, dict[str, bool]], policy: Policy
    ) -> list[Finding]:
        findings = []
        for key in sorted(policy.absence.exempt):
            path, _, name = key.partition("::")
            if path not in measured:
                message = "names no file"
            elif name not in measured[path]:
                message = "names no test"
            elif not measured[path][name]:
                message = "asserts a present value, so it needs no exemption"
            else:
                continue
            findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
