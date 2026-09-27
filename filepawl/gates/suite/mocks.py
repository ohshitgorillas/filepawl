"""Mocks gate: no test replaces a collaborator with a stand-in (design.md §6.14).

A test that patches a function, an attribute, a class or a mapping tests the
stand-in, whatever the patch replaces, own code or third-party.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.suite.common import Imports, SiteGate, units

_PATCH = "patch"
_PATCH_MEMBERS = frozenset({"object", "dict", "multiple"})
_ATTR_CALLS = frozenset({"setattr", "delattr"})
_ITEM_CALLS = frozenset({"setitem", "delitem"})
_PROCESS_MAPPINGS = frozenset({"sys.modules", "os.environ"})
_MOCKS = frozenset(
    {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"}
)
_SPEC_KEYWORDS = frozenset({"spec", "spec_set"})
_AUTOSPEC = "create_autospec"


def imported_names(module: ast.Module) -> frozenset[str]:
    """Return every name an import statement in the module binds, a relative
    import included."""
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".", 1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name != "*"
            )
    return frozenset(names)


def _root(node: ast.expr) -> str | None:
    """Return the root name of a plain name or attribute chain, or None."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _last(node: ast.expr) -> str | None:
    """Return the last name of a plain name or attribute, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_patch_call(func: ast.expr) -> bool:
    """Return whether a callee is `patch`, a chain ending in `patch`, or
    `object`, `dict` or `multiple` on such a chain."""
    if _last(func) == _PATCH:
        return True
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _PATCH_MEMBERS
        and _last(func.value) == _PATCH
    )


def _is_process_mapping(node: ast.Call, imports: Imports) -> bool:
    """Return whether a `setitem` or `delitem` call's first argument is
    `sys.modules` or `os.environ`."""
    return bool(node.args) and imports.dotted(node.args[0]) in _PROCESS_MAPPINGS


def _call_patches(node: ast.Call, imports: Imports, imported: frozenset[str]) -> bool:
    func = node.func
    last = _last(func)
    if _is_patch_call(func) or last == _AUTOSPEC:
        return True
    if last in _MOCKS:
        return any(keyword.arg in _SPEC_KEYWORDS for keyword in node.keywords)
    if isinstance(func, ast.Attribute):
        if func.attr in _ATTR_CALLS:
            return True
        return func.attr in _ITEM_CALLS and not _is_process_mapping(node, imports)
    if isinstance(func, ast.Name) and func.id in _ATTR_CALLS and node.args:
        return _root(node.args[0]) in imported
    return False


def _targets(node: ast.AST) -> list[ast.expr]:
    """Return the targets an assignment, augmented assignment or `del` binds,
    tuple, list and starred targets unpacked."""
    if isinstance(node, ast.Assign):
        pending = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        pending = [node.target]
    elif isinstance(node, ast.Delete):
        pending = list(node.targets)
    else:
        return []
    found: list[ast.expr] = []
    while pending:
        target = pending.pop()
        if isinstance(target, (ast.Tuple, ast.List)):
            pending.extend(target.elts)
        elif isinstance(target, ast.Starred):
            pending.append(target.value)
        else:
            found.append(target)
    return found


def _rebinds(node: ast.AST, imported: frozenset[str]) -> bool:
    """Return whether a statement binds or deletes an attribute on a chain
    rooted at an imported name."""
    return any(
        isinstance(target, ast.Attribute) and _root(target) in imported
        for target in _targets(node)
    )


def _patches(node: ast.AST, imports: Imports, imported: frozenset[str]) -> bool:
    if isinstance(node, ast.Call):
        return _call_patches(node, imports, imported)
    return _rebinds(node, imported)


@dataclass
class MocksGate(SiteGate):
    """Refuses tests that patch, rebind an imported name, or build a spec mock."""

    name: str = "mocks"
    fix: str = "fake at the wire, never a patch"
    clean: str = "patches nothing, so it needs no exemption"

    def sites(
        self, module: ast.Module, imports: Imports, policy: Policy
    ) -> list[tuple[str, int, str]]:
        imported = imported_names(module)
        return [
            (unit, getattr(node, "lineno", 0), _PATCH)
            for unit, node in units(module)
            if _patches(node, imports, imported)
        ]

    def describe(self, details: list[str]) -> str:
        return "patches"
