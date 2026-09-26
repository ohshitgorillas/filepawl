"""Named-results gate: no mapping of unnamed shape in a result (design.md §6.9).

A function annotated `-> dict[str, Any]` hands its caller a record whose
keys no type checker sees; an alias of one names the record without
naming its shape.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import block_bodies
from filepawl.state import State
from filepawl.tree import Tree, glob_match

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_MAPPINGS = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_LOOSE = frozenset({"Any", "object"})
_UNIONS = frozenset({"Optional", "Union"})

# (qualified name, message) per failing function or alias, in source order.
_Found = list[tuple[str, str]]


def _name(node: ast.expr) -> str | None:
    """Return a bare name, or the last part of an attribute chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _read(node: ast.expr) -> ast.expr | None:
    """Return an annotation, parsing a string constant; None when it does not parse."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return node
    try:
        return ast.parse(node.value, mode="eval").body
    except (SyntaxError, ValueError):
        # A string that does not parse names no type, so there is nothing to read.
        pass
    return None


def _items(node: ast.Subscript) -> list[ast.expr]:
    return list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]


def _holds_loose(node: ast.expr) -> bool:
    """Return whether a value type is Any or object, or a union with one as a member."""
    read = _read(node)
    if read is None:
        return False
    if _name(read) in _LOOSE:
        return True
    if isinstance(read, ast.BinOp) and isinstance(read.op, ast.BitOr):
        return _holds_loose(read.left) or _holds_loose(read.right)
    if isinstance(read, ast.Subscript) and _name(read.value) in _UNIONS:
        return any(_holds_loose(item) for item in _items(read))
    return False


def is_loose(node: ast.expr) -> bool:
    """Return whether an annotation names a mapping of unnamed shape anywhere in it."""
    read = _read(node)
    if read is None:
        return False
    if isinstance(read, ast.Subscript):
        base = _name(read.value)
        if base == "Literal":
            return False
        items = _items(read)
        if base in _MAPPINGS and _holds_loose(items[-1]):
            return True
        return any(is_loose(item) for item in items)
    if _name(read) in _MAPPINGS:
        return True
    children = ast.iter_child_nodes(read)
    return any(is_loose(child) for child in children if isinstance(child, ast.expr))


def _is_type_shaped(node: ast.expr) -> bool:
    """Return whether an assigned value can be a type: a subscript, `|`, or name."""
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, ast.BitOr)
    return isinstance(node, (ast.Subscript, ast.Name, ast.Attribute))


def _aliases(node: ast.stmt) -> list[tuple[str, ast.expr]]:
    """Return (alias name, value) for each alias a module-level statement defines."""
    if isinstance(node, ast.TypeAlias):
        return [(node.name.id, node.value)]
    if isinstance(node, ast.AnnAssign):
        target, value = node.target, node.value
        is_alias = _name(node.annotation) == "TypeAlias"
        if is_alias and isinstance(target, ast.Name) and value is not None:
            return [(target.id, value)]
        return []
    if isinstance(node, ast.Assign) and _is_type_shaped(node.value):
        return [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
    return []


def _message(verb: str, node: ast.expr) -> str:
    return f"{verb} an unnamed mapping ({ast.unparse(node)}) — name its shape"


def _function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, found: _Found
) -> None:
    """Record a function whose return annotation is loose, then its nested functions."""
    name = f"{prefix}{node.name}"
    if node.returns is not None and is_loose(node.returns):
        found.append((name, _message("returns", node.returns)))
    _walk(node.body, f"{name}.", False, found)


def _walk(body: list[ast.stmt], prefix: str, module_level: bool, found: _Found) -> None:
    """Record loose functions in a statement list, and loose aliases at module level."""
    for node in body:
        if isinstance(node, _FUNCS):
            _function(node, prefix, found)
        elif isinstance(node, ast.ClassDef):
            _walk(node.body, f"{prefix}{node.name}.", False, found)
        else:
            if module_level:
                found += [
                    (alias, _message("aliases", value))
                    for alias, value in _aliases(node)
                    if is_loose(value)
                ]
            for inner in block_bodies(node):
                _walk(inner, prefix, module_level, found)


def loose_results(module: ast.Module) -> _Found:
    """Return (qualified name, message) for each loose function and alias."""
    found: _Found = []
    _walk(module.body, "", True, found)
    return found


@dataclass
class NamedResultsGate:
    """Refuses return annotations and aliases that name a mapping of unnamed shape."""

    name: str = "named_results"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        findings: list[Finding] = []
        for path in self._checked(tree, policy):
            try:
                text = (tree.root / path).read_text(encoding="utf-8")
                module = ast.parse(text, filename=path)
            except (SyntaxError, UnicodeDecodeError):
                # Syntax is the compiler's gate; a file that does not parse
                # has no annotation to judge.
                continue
            findings += [
                Finding(f"{path}::{name}", message)
                for name, message in loose_results(module)
            ]
        return sorted(findings)

    def _checked(self, tree: Tree, policy: Policy) -> list[str]:
        include = policy.named_results.include
        exclude = policy.named_results.exclude
        return [
            path
            for path in tree.files
            if not tree.is_test(path)
            and any(glob_match(g, path) for g in include)
            and not any(glob_match(g, path) for g in exclude)
        ]

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
