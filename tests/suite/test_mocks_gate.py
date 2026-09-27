"""Tests for filepawl.gates.suite.mocks: the mocks gate (design.md §6.14)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SuiteGatePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.mocks import MocksGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

PATH = "tests/test_m.py"
FIX = " — fake at the wire, never a patch"
OWN = {"pkg/__init__.py": "", "pkg/m.py": "table = {}\n"}
IMPORTS = "import os\nimport sys\nimport json\nfrom pkg import m\n"


def _policy(**mocks: object) -> Policy:
    suite = SuitePolicies(mocks=SuiteGatePolicy(**mocks))  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=suite)


def _run(root: Path, policy: Policy) -> list[Finding]:
    return MocksGate().run(build_tree(root, policy), policy, State())


def _gate(
    repo: RepoFactory, source: str, policy: Policy | None = None
) -> list[Finding]:
    root = repo({**OWN, PATH: source})
    return _run(root, policy or _policy())


def _body(*lines: str, head: str = IMPORTS) -> str:
    return (
        head
        + "def test_f(obj, monkeypatch, mocker):\n"
        + "".join(f"    {line}\n" for line in lines)
    )


def _line(head: str = IMPORTS) -> int:
    return head.count("\n") + 2


def _finding(lines: str, unit: str = "test_f") -> Finding:
    return Finding(f"{PATH}::{unit}", f"patches at {lines}{FIX}")


PATCH_FORMS = [
    "patch('{own}')",
    "mock.patch('{own}')",
    "unittest.mock.patch('{own}')",
    "mocker.patch('{own}')",
    "patch.object({obj}, 'f')",
    "mock.patch.object({obj}, 'f')",
    "mocker.patch.object({obj}, 'f')",
    "patch.dict('{own}', {{}})",
    "mocker.patch.dict('{own}', {{}})",
    "patch.multiple({obj}, f=1)",
    "mocker.patch.multiple({obj}, f=1)",
]
TARGETS = [
    pytest.param("pkg.m.table", "m", id="own"),
    pytest.param("json.decoder.table", "json", id="third-party"),
]


@pytest.mark.parametrize("form", PATCH_FORMS)
@pytest.mark.parametrize(("dotted", "obj"), TARGETS)
def test_each_patch_form_fails_whatever_its_target(
    repo: RepoFactory, form: str, dotted: str, obj: str
) -> None:
    line = form.format(own=dotted, obj=obj)
    assert _gate(repo, _body(line)) == [_finding(f"line {_line()}")]


def test_patch_dict_on_os_environ_fails(repo: RepoFactory) -> None:
    source = _body("patch.dict(os.environ, {'A': '1'})")
    assert _gate(repo, source) == [_finding(f"line {_line()}")]


def test_patch_as_decorator_and_context_manager_fails(repo: RepoFactory) -> None:
    source = (
        IMPORTS
        + "@patch('pkg.m.f')\n"
        + "def test_f(obj):\n"
        + "    with mock.patch.object(m, 'g'):\n"
        + "        pass\n"
    )
    assert _gate(repo, source) == [_finding("lines 5, 7")]


MONKEYPATCH = [
    "monkeypatch.setattr('pkg.m.f', 1)",
    "monkeypatch.setattr(m, 'f', 1)",
    "monkeypatch.setattr('json.loads', 1)",
    "monkeypatch.setattr(json, 'loads', 1)",
    "monkeypatch.delattr('pkg.m.f')",
    "monkeypatch.delattr(m, 'f')",
    "monkeypatch.delattr('json.loads')",
    "monkeypatch.delattr(json, 'loads')",
    "monkeypatch.setattr(obj, 'f', 1)",
]


@pytest.mark.parametrize("line", MONKEYPATCH)
def test_monkeypatch_setattr_and_delattr_fail_in_both_forms(
    repo: RepoFactory, line: str
) -> None:
    assert _gate(repo, _body(line)) == [_finding(f"line {_line()}")]


REBINDS = [
    "setattr({root}.f, 'g', 1)",
    "setattr({root}, 'f', 1)",
    "delattr({root}, 'f')",
    "{root}.f = 1",
    "{root}.f.g = 1",
    "{root}.f += 1",
    "{root}.f: int = 1",
    "a, {root}.f = 1, 2",
    "del {root}.f",
]
IMPORTED = [
    pytest.param("import pkg.m\n", "pkg", id="import"),
    pytest.param("import pkg.m as alias\n", "alias", id="import-as"),
    pytest.param("from pkg import m\n", "m", id="from"),
    pytest.param("import json\n", "json", id="third-party"),
    pytest.param("import sys\n", "sys", id="stdlib"),
    pytest.param("from . import helpers\n", "helpers", id="relative"),
    pytest.param("from .helpers import fake\n", "fake", id="relative-from"),
]


@pytest.mark.parametrize("form", REBINDS)
@pytest.mark.parametrize(("head", "root"), IMPORTED)
def test_rebinding_on_an_imported_name_fails(
    repo: RepoFactory, form: str, head: str, root: str
) -> None:
    source = _body(form.format(root=root), head=head)
    assert _gate(repo, source) == [_finding(f"line {_line(head)}")]


def test_import_inside_a_function_makes_an_imported_name(repo: RepoFactory) -> None:
    source = _body("import json", "json.loads = 1", head="")
    assert _gate(repo, source) == [_finding("line 3")]


@pytest.mark.parametrize("form", REBINDS)
def test_rebinding_on_a_local_object_passes(repo: RepoFactory, form: str) -> None:
    source = _body(form.format(root="obj"), "local = Thing()", "local.f = 1")
    assert _gate(repo, source + "    self.f = 1\n") == []


MOCKS = [
    "Mock(spec=Thing)",
    "Mock(spec_set=Thing)",
    "MagicMock(spec=Thing)",
    "AsyncMock(spec=Thing)",
    "NonCallableMock(spec=Thing)",
    "NonCallableMagicMock(spec_set=Thing)",
    "mock.Mock(spec=['a'])",
    "unittest.mock.MagicMock(spec=None)",
    "mocker.MagicMock(spec_set=Thing)",
    "create_autospec(Thing)",
    "mock.create_autospec(json.loads)",
    "mocker.create_autospec(Thing)",
]


@pytest.mark.parametrize("line", MOCKS)
def test_mock_with_a_spec_and_create_autospec_fail(
    repo: RepoFactory, line: str
) -> None:
    assert _gate(repo, _body(line)) == [_finding(f"line {_line()}")]


@pytest.mark.parametrize(
    "line",
    [
        "Mock()",
        "MagicMock(return_value=1)",
        "mock.AsyncMock(side_effect=ValueError)",
        "mocker.MagicMock(name='x')",
    ],
)
def test_mock_without_a_spec_passes(repo: RepoFactory, line: str) -> None:
    assert _gate(repo, _body(line)) == []


PROCESS_STATE = [
    "monkeypatch.chdir(obj)",
    "monkeypatch.setenv('A', '1')",
    "monkeypatch.delenv('A', raising=False)",
    "monkeypatch.syspath_prepend(obj)",
    "monkeypatch.setitem(sys.modules, 'x', obj)",
    "monkeypatch.delitem(sys.modules, 'x')",
    "monkeypatch.setitem(os.environ, 'A', '1')",
    "monkeypatch.delitem(os.environ, 'A')",
    "monkeypatch.setitem(modules, 'x', obj)",
    "monkeypatch.delitem(environ, 'A')",
    "monkeypatch.setitem(o.environ, 'A', '1')",
]
PROCESS_HEAD = (
    IMPORTS + "from sys import modules\nfrom os import environ\nimport os as o\n"
)


@pytest.mark.parametrize("line", PROCESS_STATE)
def test_setting_process_state_passes(repo: RepoFactory, line: str) -> None:
    assert _gate(repo, _body(line, head=PROCESS_HEAD)) == []


@pytest.mark.parametrize(
    "line",
    [
        "monkeypatch.setitem(m.table, 'k', 1)",
        "monkeypatch.delitem(m.table, 'k')",
        "monkeypatch.setitem(json.decoder.table, 'k', 1)",
        "monkeypatch.setitem(obj, 'k', 1)",
        "monkeypatch.setitem(os.environ.copy(), 'k', 1)",
        "monkeypatch.setitem(sys.path_importer_cache, 'k', 1)",
    ],
)
def test_setitem_and_delitem_on_another_mapping_fail(
    repo: RepoFactory, line: str
) -> None:
    assert _gate(repo, _body(line)) == [_finding(f"line {_line()}")]


def test_several_sites_report_once_with_every_line(repo: RepoFactory) -> None:
    source = _body("patch('pkg.m.f')", "m.table = {}", "Mock(spec=m)")
    first = _line()
    assert _gate(repo, source) == [_finding(f"lines {first}, {first + 1}, {first + 2}")]


def test_module_level_sites_report_under_module(repo: RepoFactory) -> None:
    source = _body("m.g = 1") + "m.table = {}\n"
    assert _gate(repo, source) == [
        _finding(f"line {_line() + 1}", "<module>"),
        _finding(f"line {_line()}"),
    ]


def test_nested_functions_and_methods_are_named_by_qualified_name(
    repo: RepoFactory,
) -> None:
    source = (
        "from pkg import m\n"
        "class TestT:\n"
        "    def test_a(self):\n"
        "        def inner():\n"
        "            m.f = 1\n"
        "        patch('pkg.m.g')\n"
    )
    assert _gate(repo, source) == [
        _finding("line 6", "TestT.test_a"),
        _finding("line 5", "TestT.test_a.inner"),
    ]


def test_non_test_paths_and_files_outside_include_are_not_checked(
    repo: RepoFactory,
) -> None:
    bad = _body("patch('pkg.m.f')")
    root = repo({**OWN, "pkg/helper.py": bad, "tests/other.py": bad, PATH: bad})
    assert _run(root, _policy(include=(PATH,))) == [_finding(f"line {_line()}")]


def test_file_that_does_not_parse_is_skipped(repo: RepoFactory) -> None:
    root = repo(
        {**OWN, "tests/test_broken.py": "def test_(:\n", PATH: _body("m.f = 1")}
    )
    assert _run(root, _policy()) == [_finding(f"line {_line()}")]


def _stale(key: str, message: str) -> Finding:
    return Finding("pyproject.toml", f"[tool.filepawl.mocks.exempt] {key!r}: {message}")


def test_exempt_unit_passes_and_others_still_fail(repo: RepoFactory) -> None:
    source = _body("m.f = 1") + "def test_g():\n    m.g = 1\n"
    policy = _policy(exempt={f"{PATH}::test_f": "reason"})
    assert _gate(repo, source, policy) == [_finding(f"line {_line() + 2}", "test_g")]


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("tests/test_gone.py::test_f", "names no file"),
        ("pkg/m.py::f", "names no file"),
        (f"{PATH}::test_missing", "names no function"),
        (f"{PATH}::test_clean", "patches nothing, so it needs no exemption"),
    ],
)
def test_stale_exemption_fails(repo: RepoFactory, key: str, message: str) -> None:
    source = _body("m.f = 1") + "def test_clean(obj):\n    obj.f = 1\n"
    policy = _policy(exempt={key: "reason"})
    assert _gate(repo, source, policy) == [
        _stale(key, message),
        _finding(f"line {_line()}"),
    ]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "mocks"],
        [gate.name for gate in off if gate.name == "mocks"],
    ) == ([MocksGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({**OWN, PATH: _body("m.f = 1")})
    state = State()
    policy = _policy()
    assert MocksGate().accept(build_tree(root, policy), policy, state) is state
