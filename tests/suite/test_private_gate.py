"""Tests for filepawl.gates.suite.private: the private gate (design.md §6.13)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SuiteGatePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.private import PrivateGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

PATH = "tests/test_m.py"
FIX = " — test through the public surface"
OWN = {"pkg/__init__.py": "", "pkg/m.py": "x = 1\n", "pkg/_m.py": "x = 1\n"}


def _policy(**private: object) -> Policy:
    suite = SuitePolicies(private=SuiteGatePolicy(**private))  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=suite)


def _run(root: Path, policy: Policy) -> list[Finding]:
    return PrivateGate().run(build_tree(root, policy), policy, State())


def _gate(
    repo: RepoFactory, source: str, policy: Policy | None = None
) -> list[Finding]:
    root = repo({**OWN, PATH: source})
    return _run(root, policy or _policy())


def _body(*lines: str) -> str:
    return "def test_f(obj, monkeypatch, mocker):\n" + "".join(
        f"    {line}\n" for line in lines
    )


def _finding(names: str, lines: str, unit: str = "test_f") -> Finding:
    return Finding(f"{PATH}::{unit}", f"reaches {names} at {lines}{FIX}")


REACHES = [
    ("x = obj._secret", "_secret"),
    ("obj._secret = 1", "_secret"),
    ("del obj._secret", "_secret"),
    ("x = obj.__mangled", "__mangled"),
    ("getattr(obj, '_secret')", "_secret"),
    ("hasattr(obj, '_secret')", "_secret"),
    ("monkeypatch.setattr(obj, '_secret', 1)", "_secret"),
    ("monkeypatch.delattr(obj, '_secret')", "_secret"),
    ("patch.object(obj, '_secret')", "_secret"),
    ("mocker.patch.object(obj, '_secret')", "_secret"),
    ("monkeypatch.setattr('pkg.m._secret', 1)", "_secret"),
    ("patch('pkg._m.f')", "_m"),
    ("mocker.patch('pkg.m._f')", "_f"),
    ("import pkg._m", "_m"),
    ("from pkg._m import f", "_m"),
    ("from pkg.m import _f", "_f"),
    ("from pkg import _m", "_m"),
]


@pytest.mark.parametrize(("line", "name"), REACHES)
def test_each_private_reach_fails(repo: RepoFactory, line: str, name: str) -> None:
    assert _gate(repo, _body(line)) == [_finding(name, "line 2")]


PASSES = [
    "x = obj.public",
    "x = obj.__dict__",
    "x = obj._asdict()",
    "x = obj._replace(a=1)",
    "x = obj._fields",
    "getattr(obj, 'public')",
    "monkeypatch.setattr(obj, 'public', 1)",
    "monkeypatch.setattr('pkg.m.public', 1)",
    "patch('other._m.f')",
    "from _pytest import fixtures",
    "import other._m",
    "from other.m import _f",
    "from ._helpers import _f",
]


@pytest.mark.parametrize("line", PASSES)
def test_public_reach_passes_beside_a_private_one(repo: RepoFactory, line: str) -> None:
    assert _gate(repo, _body(line, "x = obj._secret")) == [
        _finding("_secret", "line 3")
    ]


def test_self_and_cls_receivers_pass(repo: RepoFactory) -> None:
    source = (
        "class Helper:\n"
        "    def a(self):\n"
        "        return self._x\n"
        "    @classmethod\n"
        "    def b(cls):\n"
        "        return cls._y, self_like._z\n"
    )
    assert _gate(repo, source) == [_finding("_z", "line 6", "Helper.b")]


def test_names_the_file_defines_are_its_own(repo: RepoFactory) -> None:
    source = (
        "def _helper():\n"
        "    pass\n"
        "class _Fake:\n"
        "    def __init__(self):\n"
        "        self._calls = []\n"
        "_table = {}\n"
        + _body("x = obj._helper, obj._Fake, obj._calls, obj._table, obj._other")
    )
    assert _gate(repo, source) == [_finding("_other", "line 8")]


def test_a_write_on_another_object_does_not_make_a_name_the_files_own(
    repo: RepoFactory,
) -> None:
    source = _body("obj._state = 1", "x = obj._state")
    assert _gate(repo, source) == [_finding("_state", "lines 2, 3")]


def test_several_sites_list_names_once_and_every_line(repo: RepoFactory) -> None:
    source = _body("x = obj._a", "y = obj._b", "z = obj._a")
    assert _gate(repo, source) == [_finding("_a, _b", "lines 2, 3, 4")]


def test_module_level_sites_report_under_module(repo: RepoFactory) -> None:
    source = "from pkg.m import _f\n" + _body("x = obj._g")
    assert _gate(repo, source) == [
        _finding("_f", "line 1", "<module>"),
        _finding("_g", "line 3"),
    ]


def test_nested_functions_and_methods_are_named_by_qualified_name(
    repo: RepoFactory,
) -> None:
    source = (
        "class TestT:\n"
        "    def test_a(self, obj):\n"
        "        def inner():\n"
        "            return obj._x\n"
        "        return obj._y\n"
    )
    assert _gate(repo, source) == [
        _finding("_y", "line 5", "TestT.test_a"),
        _finding("_x", "line 4", "TestT.test_a.inner"),
    ]


def test_decorator_belongs_to_the_function_it_decorates(repo: RepoFactory) -> None:
    source = "@patch.object(Thing, '_x')\n" + _body("pass")
    assert _gate(repo, source) == [_finding("_x", "line 1")]


def test_own_names_come_from_policy_packages(repo: RepoFactory) -> None:
    source = _body("from lib import _f", "from pkg import _g")
    policy = dataclasses.replace(_policy(), packages=("lib",))
    assert _gate(repo, source, policy) == [_finding("_f", "line 2")]


def test_non_test_paths_and_files_outside_include_are_not_checked(
    repo: RepoFactory,
) -> None:
    bad = _body("x = obj._secret")
    root = repo({**OWN, "pkg/helper.py": bad, "tests/other.py": bad, PATH: bad})
    policy = _policy(include=(PATH,))
    assert _run(root, policy) == [_finding("_secret", "line 2")]


def test_file_that_does_not_parse_is_skipped(repo: RepoFactory) -> None:
    root = repo({**OWN, "tests/test_broken.py": "def test_(:\n", PATH: _body("obj._x")})
    assert _run(root, _policy()) == [_finding("_x", "line 2")]


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.private.exempt] {key!r}: {message}"
    )


def test_exempt_unit_passes_and_others_still_fail(repo: RepoFactory) -> None:
    source = _body("x = obj._a") + "def test_g(obj):\n    x = obj._b\n"
    policy = _policy(exempt={f"{PATH}::test_f": "reason"})
    assert _gate(repo, source, policy) == [_finding("_b", "line 4", "test_g")]


def test_module_unit_can_be_exempted(repo: RepoFactory) -> None:
    source = "from pkg.m import _f\n" + _body("x = obj._g")
    policy = _policy(exempt={f"{PATH}::<module>": "reason"})
    assert _gate(repo, source, policy) == [_finding("_g", "line 3")]


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("tests/test_gone.py::test_f", "names no file"),
        ("pkg/m.py::f", "names no file"),
        (f"{PATH}::test_missing", "names no function"),
        (f"{PATH}::test_clean", "reaches no private name, so it needs no exemption"),
    ],
)
def test_stale_exemption_fails(repo: RepoFactory, key: str, message: str) -> None:
    source = _body("x = obj._a") + "def test_clean(obj):\n    x = obj.b\n"
    policy = _policy(exempt={key: "reason"})
    assert _gate(repo, source, policy) == [
        _stale(key, message),
        _finding("_a", "line 2"),
    ]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "private"],
        [gate.name for gate in off if gate.name == "private"],
    ) == ([PrivateGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({**OWN, PATH: _body("x = obj._a")})
    state = State()
    policy = _policy()
    assert PrivateGate().accept(build_tree(root, policy), policy, state) is state
