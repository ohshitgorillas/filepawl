"""Tests for filepawl.gates.reach: the reach gate (design.md §6.21)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_code import ReachPolicy
from filepawl.gates.base import Finding
from filepawl.gates.reach import ReachGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

OWN = {
    "pkg/__init__.py": "_flag = 1\n",
    "pkg/mod.py": "_attr = 1\npublic = 2\n",
    "pkg/_impl.py": "helper = 1\n_inner = 2\n",
    "pkg/sub/__init__.py": "",
    "pkg/sub/deep.py": "_deep = 1\n",
}
PATH = "pkg/user.py"
FIX = " — make it public where it lives, or move it to its one user"


def _reaches(name: str, source: str, lines: str = "line 1") -> Finding:
    return Finding(
        f"{PATH}::{name}", f"imports private {name} from {source} at {lines}{FIX}"
    )


def _policy(**reach: object) -> Policy:
    return dataclasses.replace(
        default_policy(), reach=ReachPolicy(**reach)  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return ReachGate().run(build_tree(root, policy), policy, State())


def _gate(
    repo: RepoFactory, source: str, policy: Policy | None = None
) -> list[Finding]:
    root = repo({**OWN, PATH: source})
    return _run(root, policy or _policy())


def _stale(key: str, message: str) -> Finding:
    return Finding("pyproject.toml", f"[tool.filepawl.reach.exempt] {key!r}: {message}")


class TestPrivateImports:
    def test_absolute_private_import_fails_and_public_passes(
        self, repo: RepoFactory
    ) -> None:
        found = _gate(repo, "from pkg.mod import _attr, public\n")
        assert found == [_reaches("_attr", "pkg.mod")]

    @pytest.mark.parametrize(
        ("statement", "source"),
        [
            ("from .mod import _attr\n", "pkg.mod"),
            ("from . import _flag\n", "pkg"),
            ("from .sub.deep import _deep\n", "pkg.sub.deep"),
            ("from pkg._impl import _inner\n", "pkg._impl"),
        ],
    )
    def test_relative_and_private_module_sources_resolve(
        self, repo: RepoFactory, statement: str, source: str
    ) -> None:
        name = statement.split("import ")[1].strip()
        assert _gate(repo, statement) == [_reaches(name, source)]

    def test_relative_import_from_a_nested_package_climbs(
        self, repo: RepoFactory
    ) -> None:
        root = repo({**OWN, "pkg/sub/user.py": "from ..mod import _attr\n"})
        message = f"imports private _attr from pkg.mod at line 1{FIX}"
        assert _run(root, _policy()) == [Finding("pkg/sub/user.py::_attr", message)]

    @pytest.mark.parametrize(
        "statement",
        [
            "from pkg import _impl\n",
            "from . import _impl\n",
            "from pkg._impl import helper\n",
            "from pkg.mod import __doc__\n",
            "from yaml import _private\n",
            "from pkg.mod import *\n",
            "import pkg._impl\n",
        ],
    )
    def test_module_dunder_third_party_star_and_plain_import_pass(
        self, repo: RepoFactory, statement: str
    ) -> None:
        source = statement + "from pkg.mod import _attr\n"
        assert _gate(repo, source) == [_reaches("_attr", "pkg.mod", "line 2")]

    def test_private_module_under_src_layout_passes(self, repo: RepoFactory) -> None:
        root = repo(
            {
                "src/pkg/__init__.py": "",
                "src/pkg/_impl.py": "x = 1\n",
                "src/pkg/mod.py": "_attr = 1\n",
                "src/pkg/user.py": "from pkg import _impl\nfrom pkg.mod import _attr\n",
            }
        )
        message = f"imports private _attr from pkg.mod at line 2{FIX}"
        assert _run(root, _policy()) == [Finding("src/pkg/user.py::_attr", message)]

    def test_alias_nested_scope_and_repeats_are_one_finding_per_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from pkg.mod import _attr as attr\n"
            "def f() -> int:\n"
            "    from pkg.mod import _attr\n"
            "    from pkg.sub.deep import _deep\n"
            "    return _attr + _deep\n"
        )
        assert _gate(repo, source) == [
            _reaches("_attr", "pkg.mod", "lines 3, 5"),
            _reaches("_deep", "pkg.sub.deep", "line 6"),
        ]

    def test_packages_policy_names_own_code(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(_policy(), packages=("other",))
        root = repo(
            {
                **OWN,
                "other.py": "_x = 1\n",
                PATH: "from pkg.mod import _attr\nfrom other import _x\n",
            }
        )
        message = f"imports private _x from other at line 2{FIX}"
        assert _run(root, policy) == [Finding(f"{PATH}::_x", message)]


class TestFileSet:
    def test_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        reach = "from pkg.mod import _attr\n"
        root = repo({**OWN, "tests/test_m.py": reach, PATH: reach})
        assert _run(root, _policy()) == [_reaches("_attr", "pkg.mod")]

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        reach = "from pkg.mod import _attr\n"
        root = repo({**OWN, "scripts/s.py": reach, PATH: reach})
        policy = _policy(include=("pkg/**",))
        assert _run(root, policy) == [_reaches("_attr", "pkg.mod")]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo(
            {**OWN, "pkg/bad.py": "def f(:\n", PATH: "from pkg.mod import _attr\n"}
        )
        assert _run(root, _policy()) == [_reaches("_attr", "pkg.mod")]


class TestExemptions:
    def test_exempt_name_passes(self, repo: RepoFactory) -> None:
        root = repo({**OWN, PATH: "from pkg.mod import _attr\n"})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={f"{PATH}::_attr": "shared with its twin"}))
        assert (plain, exempt) == ([_reaches("_attr", "pkg.mod")], [])

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        found = _gate(repo, "x = 1\n", _policy(exempt={"gone.py::_x": "r"}))
        assert found == [_stale("gone.py::_x", "names no file")]

    def test_entry_naming_a_name_not_reached_fails(self, repo: RepoFactory) -> None:
        policy = _policy(exempt={f"{PATH}::_other": "r"})
        found = _gate(repo, "from pkg.mod import _attr\n", policy)
        assert found == [
            _reaches("_attr", "pkg.mod"),
            _stale(
                f"{PATH}::_other",
                "imports no such private name, so it needs no exemption",
            ),
        ]


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({**OWN, PATH: "from pkg.mod import _attr\n"})
    policy = _policy()
    state = State()
    assert ReachGate().accept(build_tree(root, policy), policy, state) is state
