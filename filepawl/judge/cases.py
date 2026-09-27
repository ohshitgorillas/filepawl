"""Judge cases: silenced findings between two trees, with their sources (§7.2).

A case is a function that the handlers or returns gate fails in the old
version of a file and that, in the new version at the same path, exists
and passes. The old tree is `HEAD` and the new one the index, or, for
`--head`, `HEAD`'s first parent and `HEAD`.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from filepawl.config import Policy
from filepawl.errors import FilepawlError
from filepawl.gates import handlers, returns
from filepawl.gates.nesting import block_bodies
from filepawl.tree import glob_match

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_INDEX = ""

_Measure = Callable[[ast.Module], frozenset[str]]


@dataclass(frozen=True)
class Case:
    """One silenced finding: its gate, key, both sources and the new helpers."""

    gate: str
    key: str
    old: str
    new: str
    # (qualified name, source) per function the new version adds, in source order.
    helpers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Gate:
    name: str
    include: tuple[str, ...]
    measure: _Measure


@dataclass(frozen=True)
class _Version:
    """One version of a file: its module and each function's source by name."""

    module: ast.Module
    sources: dict[str, str]


def find_cases(root: Path, policy: Policy, head: bool) -> list[Case]:
    """Return the cases between the two trees a run compares, exempt keys dropped."""
    old_rev, new_rev = ("HEAD^", "HEAD") if head else ("HEAD", _INDEX)
    if not _exists(root, old_rev):
        # A root commit, or a repository with no commit, has nothing to compare.
        return []
    gates = _enabled_gates(policy)
    cases: list[Case] = []
    for path in _modified(root, old_rev, new_rev):
        checked = [gate for gate in gates if _checks(policy, gate.include, path)]
        if not checked:
            continue
        try:
            old = _version(_show(root, old_rev, path), path)
            new = _version(_show(root, new_rev, path), path)
        except (SyntaxError, UnicodeDecodeError):
            # Syntax is the compiler's gate; a version that does not parse
            # has no function for either gate to measure.
            continue
        cases += _file_cases(path, old, new, checked)
    exempt = policy.judge.exempt
    kept = [case for case in cases if case.key not in exempt]
    return sorted(kept, key=lambda case: (case.key, case.gate))


def _enabled_gates(policy: Policy) -> list[_Gate]:
    gates = [
        _Gate("handlers", policy.handlers.include, handlers.failing_names),
        _Gate("returns", policy.returns.include, returns.failing_names),
    ]
    enabled = {"handlers": policy.handlers.enabled, "returns": policy.returns.enabled}
    return [gate for gate in gates if enabled[gate.name]]


def _checks(policy: Policy, include: tuple[str, ...], path: str) -> bool:
    """Whether a gate's checked files (§6.8, §6.10) take in a Python file at `path`."""
    languages = [g for language in policy.languages.values() for g in language.include]
    return (
        path.endswith(".py")
        and any(glob_match(g, path) for g in languages)
        and any(glob_match(g, path) for g in include)
        and not any(glob_match(g, path) for g in policy.tests)
    )


def _file_cases(
    path: str, old: _Version, new: _Version, gates: list[_Gate]
) -> list[Case]:
    helpers = tuple(
        (name, source)
        for name, source in new.sources.items()
        if name not in old.sources
    )
    cases: list[Case] = []
    for gate in gates:
        silenced = gate.measure(old.module) - gate.measure(new.module)
        cases += [
            Case(
                gate.name,
                f"{path}::{name}",
                old.sources[name],
                new.sources[name],
                helpers,
            )
            for name in sorted(silenced)
            if name in new.sources
        ]
    return cases


def _version(blob: bytes, path: str) -> _Version:
    text = blob.decode("utf-8")
    module = ast.parse(text, filename=path)
    found: dict[str, list[str]] = {}
    _collect(module.body, "", text.splitlines(), found)
    return _Version(module, {name: "\n\n".join(s) for name, s in found.items()})


def _collect(
    body: list[ast.stmt], prefix: str, lines: list[str], found: dict[str, list[str]]
) -> None:
    """Add each function's source under its qualified name, as the gates name it."""
    for node in body:
        if isinstance(node, _FUNCS):
            name = f"{prefix}{node.name}"
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno or node.lineno
            found.setdefault(name, []).append("\n".join(lines[start - 1 : end]))
            _collect(node.body, f"{name}.", lines, found)
        elif isinstance(node, ast.ClassDef):
            _collect(node.body, f"{prefix}{node.name}.", lines, found)
        else:
            for inner in block_bodies(node):
                _collect(inner, prefix, lines, found)


def _exists(root: Path, rev: str) -> bool:
    verify = ["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"]
    return subprocess.run(verify, cwd=root, capture_output=True).returncode == 0


def _modified(root: Path, old_rev: str, new_rev: str) -> list[str]:
    """Return each path present in both trees whose content differs."""
    revs = ["--cached", old_rev] if new_rev == _INDEX else [old_rev, new_rev]
    args = ["diff", "--no-renames", "--name-only", "--diff-filter=M", "-z", *revs]
    return [name for name in _git(root, args).decode("utf-8").split("\0") if name]


def _show(root: Path, rev: str, path: str) -> bytes:
    return _git(root, ["show", f"{rev}:{path}"])


def _git(root: Path, args: list[str]) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise FilepawlError(f"git {args[0]} failed: {detail}")
    return result.stdout
