"""Tests for filepawl.gates.suite.detours: the detours gate (design.md §6.23)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SuiteGatePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.detours import DetoursGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

PATH = "tests/test_m.py"
FIX = " — assert in the test: a guard for an optional, a claim for a check"
HEAD = (
    "import pytest\n"
    "import typing\n"
    "from pytest import fail\n"
    "from typing import cast\n"
    "from typing_extensions import cast as cast_x\n"
)


def _policy(**detours: object) -> Policy:
    suite = SuitePolicies(detours=SuiteGatePolicy(**detours))  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=suite)


def _run(root: Path, policy: Policy) -> list[Finding]:
    return DetoursGate().run(build_tree(root, policy), policy, State())


def _gate(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines`, below the shared imports."""
    source = HEAD + "def test_f(out):\n" + "".join(f"    {line}\n" for line in lines)
    return _run(repo({PATH: source}), _policy())


def _line() -> int:
    return HEAD.count("\n") + 2


def _finding(details: str, lines: str, unit: str = "test_f") -> Finding:
    message = f"routes around an assert through {details} at {lines}{FIX}"
    return Finding(f"{PATH}::{unit}", message)


SITES = [
    ("raise AssertionError", "raise AssertionError"),
    ("raise AssertionError('boom')", "raise AssertionError"),
    ("pytest.fail('boom')", "pytest.fail"),
    ("fail('boom')", "pytest.fail"),
    ("x = cast(int, out)", "cast"),
    ("x = typing.cast(int, out)", "cast"),
    ("x = cast_x(int, out)", "cast"),
    ("x = (out or {})['k']", "or <absent>"),
    ("x = out or []", "or <absent>"),
    ("x = out or ''", "or <absent>"),
    ("x = out or None", "or <absent>"),
    ("x = out or 0", "or <absent>"),
    ("x = a or b or dict()", "or <absent>"),
    ("x = out.y  # type: ignore", "type: ignore"),
    ("x = out.y  # type: ignore[union-attr]", "type: ignore"),
    ("x = out.y  # type: ignore[attr-defined, union-attr]", "type: ignore"),
]


@pytest.mark.parametrize(("line", "detail"), SITES)
def test_each_detour_fails(repo: RepoFactory, line: str, detail: str) -> None:
    assert _gate(repo, line) == [_finding(detail, f"line {_line()}")]


@pytest.mark.parametrize(
    "line",
    [
        "raise ValueError('boom')",
        "x = other.cast(int, out)",
        "x = out or [1]",
        "x = out or default",
        "x = out and {}",
        "x = out.y  # type: ignore[attr-defined]",
        "x = '# type: ignore'",
        "assert out is not None",
    ],
)
def test_other_shapes_pass_beside_a_detour(repo: RepoFactory, line: str) -> None:
    found = _gate(repo, line, "raise AssertionError")
    assert found == [_finding("raise AssertionError", f"line {_line() + 1}")]


def test_several_detours_list_each_once_in_order(repo: RepoFactory) -> None:
    lines = ["x = cast(int, out)", "y = out or {}", "z = cast(str, out)"]
    first = _line()
    expected = _finding("cast, or <absent>", f"lines {first}, {first + 1}, {first + 2}")
    assert _gate(repo, *lines) == [expected]


def test_comments_are_reported_under_their_unit(repo: RepoFactory) -> None:
    source = (
        "X = run()  # type: ignore\n"
        "class TestThing:\n"
        "    def test_a(self):\n"
        "        x = out.y  # type: ignore[union-attr]\n"
    )
    root = repo({PATH: source})
    assert _run(root, _policy()) == [
        _finding("type: ignore", "line 1", unit="<module>"),
        _finding("type: ignore", "line 4", unit="TestThing.test_a"),
    ]


def test_non_test_paths_are_not_checked(repo: RepoFactory) -> None:
    root = repo({"pkg/m.py": "x = y or {}\n", PATH: "x = y or {}\n"})
    assert _run(root, _policy()) == [_finding("or <absent>", "line 1", "<module>")]


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.detours.exempt] {key!r}: {message}"
    )


def test_exempt_unit_passes(repo: RepoFactory) -> None:
    source = "def test_f():\n    raise AssertionError\n"
    root = repo({PATH: source})
    plain = _run(root, _policy())
    exempt = _run(root, _policy(exempt={f"{PATH}::test_f": "reason"}))
    assert (plain, exempt) == ([_finding("raise AssertionError", "line 2")], [])


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("tests/test_gone.py::test_f", "names no file"),
        (f"{PATH}::test_gone", "names no function"),
        (f"{PATH}::test_f", "routes around no assert, so it needs no exemption"),
    ],
)
def test_stale_exemption_fails(repo: RepoFactory, key: str, message: str) -> None:
    root = repo({PATH: "def test_f():\n    assert run() == 1\n"})
    assert _run(root, _policy(exempt={key: "reason"})) == [_stale(key, message)]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "detours"],
        [gate.name for gate in off if gate.name == "detours"],
    ) == ([DetoursGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({PATH: "x = y or {}\n"})
    policy = _policy()
    state = State()
    assert DetoursGate().accept(build_tree(root, policy), policy, state) is state
