"""Rules the test gates share (design.md §6.11, §6.12): what a test is, what
its assertions claim, and the engine that judges each test once."""

from __future__ import annotations

import ast

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.gates.suite.common import Stale, parsed, stale_entry
from filepawl.state import State
from filepawl.tree import Tree

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
# Nodes whose contents are not the enclosing test's own statements.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_WITHS = (ast.With, ast.AsyncWith)
_CONTEXTS = frozenset({"raises", "warns", "deprecated_call"})
_EMPTY_CALLS = frozenset({"list", "dict", "set", "tuple", "frozenset", "str", "bytes"})

TestNode = ast.FunctionDef | ast.AsyncFunctionDef


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


_NEGATED: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
}


_BOOL_CALLS = frozenset({"isinstance", "issubclass", "callable", "hasattr", "bool"})


def _is_claim(node: ast.expr) -> bool:
    """Return whether an expression yields a bool: a comparison, a `not`, or
    a bool-valued builtin call."""
    if isinstance(node, ast.Compare):
        return True
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, ast.Not)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _BOOL_CALLS
    )


def _negated(node: ast.expr) -> ast.expr:
    """Return a claim's negation: one comparison flips its operator."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        flipped = _NEGATED[type(node.ops[0])]()
        return ast.Compare(left=node.left, ops=[flipped], comparators=node.comparators)
    return ast.UnaryOp(op=ast.Not(), operand=node)


def _pair(left: ast.expr, right: ast.expr) -> ast.expr:
    """Return the claim one position of a packed tuple assertion makes."""
    for side, other in ((left, right), (right, left)):
        if not _is_claim(other):
            continue
        if isinstance(side, ast.Constant) and side.value is True:
            return other
        if isinstance(side, ast.Constant) and side.value is False:
            return _negated(other)
    return ast.Compare(left=left, ops=[ast.Eq()], comparators=[right])


def packed(test: ast.expr) -> list[ast.expr] | None:
    """Return the claims a packed tuple assertion makes, one per position, or
    None when the test is not one (design.md §6.11)."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left, right = test.left, test.comparators[0]
    if not (
        isinstance(test.ops[0], ast.Eq)
        and isinstance(left, ast.Tuple)
        and isinstance(right, ast.Tuple)
        and len(left.elts) == len(right.elts)
    ):
        return None
    if any(isinstance(elt, ast.Starred) for elt in left.elts + right.elts):
        return None
    return [_pair(a, b) for a, b in zip(left.elts, right.elts, strict=True)]


ABSENCE = "absence"
EXISTENCE = "existence"
VALUE = "value"

_EXISTENCE_CALLS = _BOOL_CALLS | {"len"}


def kind(test: ast.expr) -> str:
    """Return what an assert's test claims: ABSENCE, EXISTENCE or VALUE
    (design.md §6.11, §6.18). A packed tuple assertion claims absence when
    every pair does, a value when any pair does, and existence otherwise."""
    claims = packed(test)
    if claims is not None:
        kinds = {kind(claim) for claim in claims}
        if kinds <= {ABSENCE}:
            return ABSENCE
        return VALUE if VALUE in kinds else EXISTENCE
    if _is_absence(test):
        return ABSENCE
    return EXISTENCE if _is_existence(test) else VALUE


def is_absence_assertion(node: ast.Assert) -> bool:
    """Return whether an assert claims only that something is absent."""
    return kind(node.test) == ABSENCE


def _is_absence(test: ast.expr) -> bool:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], (ast.Eq, ast.Is)):
        return False
    return is_absent(test.left) or is_absent(test.comparators[0])


def _is_existence(test: ast.expr) -> bool:
    if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript)):
        return True
    if isinstance(test, ast.Call):
        return _called(test) in _EXISTENCE_CALLS
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    op, left, right = test.ops[0], test.left, test.comparators[0]
    if isinstance(op, (ast.IsNot, ast.NotEq)):
        return is_absent(left) or is_absent(right)
    if isinstance(op, (ast.Eq, ast.Is)):
        return _is_type_call(left) or _is_type_call(right)
    if isinstance(op, ast.In):
        return _is_key_listing(right)
    return (
        (isinstance(op, ast.Gt) and _is_int(right, 0))
        or (isinstance(op, ast.GtE) and _is_int(right, 1))
        or (isinstance(op, ast.Lt) and _is_int(left, 0))
        or (isinstance(op, ast.LtE) and _is_int(left, 1))
    )


def _called(node: ast.Call) -> str | None:
    """Return the bare name a call calls, or None."""
    return node.func.id if isinstance(node.func, ast.Name) else None


def _is_type_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and _called(node) == "type"
        and len(node.args) == 1
        and not node.keywords
    )


def _is_key_listing(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "keys"
    return _called(node) in ("vars", "dir")


def _is_int(node: ast.expr, value: int) -> bool:
    return (
        isinstance(node, ast.Constant)
        and type(node.value) is int
        and node.value == value
    )


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


def _collect(node: ast.AST, asserts: list[ast.Assert]) -> bool:
    """Collect the test's own asserts; return whether it asserts something else."""
    if _asserts_otherwise(node):
        return True
    if isinstance(node, ast.Assert):
        asserts.append(node)
    return any(
        _collect(child, asserts)
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, _SCOPES)
    )


def own_asserts(test: TestNode) -> list[ast.Assert] | None:
    """Return a test's own asserts, or None when it asserts something else."""
    asserts: list[ast.Assert] = []
    for node in test.body:
        if isinstance(node, _SCOPES):
            continue
        if _collect(node, asserts):
            return None
    return asserts


def tests_in(module: ast.Module) -> list[tuple[str, TestNode]]:
    """Return (qualified name, node) for every test a module defines."""
    found: list[tuple[str, TestNode]] = []
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


class TestGate:
    """A gate that judges each test once (design.md §6.12)."""

    __test__ = False

    name: str
    message: str
    clean: str

    def fails(self, test: TestNode) -> bool:
        """Return whether a test fails the gate."""
        raise NotImplementedError

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        table = getattr(policy.suite, self.name)
        findings: list[Finding] = []
        measured: dict[str, dict[str, bool]] = {}
        for path, module in parsed(tree, table.include):
            judged = measured.setdefault(path, {})
            for name, test in tests_in(module):
                failed = self.fails(test)
                judged[name] = judged.get(name, False) or failed
                if failed and f"{path}::{name}" not in table.exempt:
                    findings.append(Finding(f"{path}::{name}", self.message))
        messages = Stale(missing="names no test", clean=self.clean)
        for key in sorted(table.exempt):
            stale = stale_entry(self.name, key, measured, messages)
            if stale is not None:
                findings.append(stale)
        return sorted(findings)

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
