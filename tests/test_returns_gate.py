"""Tests for filepawl.gates.returns: the returns gate (design.md §6.8)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import Policy, ReturnsPolicy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.returns import ReturnsGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

TWO_SHAPES = (
    "def f(c):\n"
    "    if c:\n"
    '        return {"a": 1, "b": 2}\n'
    '    return {"a": 1}\n'
)


def _shapes(*shapes: str) -> str:
    return (
        f"returns dicts of {len(shapes)} shapes ({'; '.join(shapes)})"
        " — return one shape"
    )


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.returns.exempt] {key!r}: {message}"
    )


def _policy(**returns: object) -> Policy:
    return dataclasses.replace(
        default_policy(), returns=ReturnsPolicy(**returns)  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return ReturnsGate().run(build_tree(root, policy), policy, State())


class TestShapes:
    def test_one_shape_passes(self, repo: RepoFactory) -> None:
        source = (
            "def f(c):\n"
            "    if c:\n"
            '        return {"a": 1, "b": 2}\n'
            '    return {"a": 3, "b": 4}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_two_shapes_fail(self, repo: RepoFactory) -> None:
        root = repo({"m.py": TWO_SHAPES})
        assert _run(root, _policy()) == [Finding("m.py::f", _shapes("{a, b}", "{a}"))]

    def test_shapes_listed_in_first_appearance_order(self, repo: RepoFactory) -> None:
        source = (
            "def f(c):\n"
            "    if c:\n"
            '        return {"z": 1}\n'
            "    if not c:\n"
            '        return {"b": 1, "a": 2}\n'
            '    return {"z": 2}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _shapes("{z}", "{a, b}"))]

    def test_key_order_and_repeats_do_not_count(self, repo: RepoFactory) -> None:
        source = (
            "def f(c):\n"
            "    if c:\n"
            '        return {"a": 1, "b": 2}\n'
            '    return {"b": 1, "a": 2, "a": 3}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_empty_dict_is_a_shape(self, repo: RepoFactory) -> None:
        source = 'def f(c):\n    if c:\n        return {}\n    return {"a": 1}\n'
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _shapes("{}", "{a}"))]

    def test_spread_literal_is_skipped(self, repo: RepoFactory) -> None:
        source = (
            "def f(c, d):\n"
            "    if c:\n"
            '        return {**d, "b": 2}\n'
            '    return {"a": 1}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_non_string_key_literal_is_skipped(self, repo: RepoFactory) -> None:
        source = (
            "def f(c, k):\n"
            "    if c:\n"
            "        return {k: 1}\n"
            "    if not c:\n"
            "        return {1: 1}\n"
            '    return {"a": 1}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_non_dict_and_bare_returns_are_ignored(self, repo: RepoFactory) -> None:
        source = (
            "def f(c, d):\n"
            "    if c:\n"
            "        return None\n"
            "    if d:\n"
            "        return\n"
            "    if c and d:\n"
            "        return dict(b=1)\n"
            "    if c or d:\n"
            "        return d\n"
            '    return {"a": 1}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_nested_def_returns_are_its_own(self, repo: RepoFactory) -> None:
        source = (
            "def outer():\n"
            "    def inner():\n"
            '        return {"b": 1}\n'
            '    return {"a": 1}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []

    def test_nested_def_is_checked_under_its_qualified_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def outer():\n"
            "    def inner(c):\n"
            "        if c:\n"
            '            return {"b": 1}\n'
            '        return {"a": 1}\n'
            "    return inner\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [
            Finding("m.py::outer.inner", _shapes("{b}", "{a}"))
        ]

    def test_method_and_async_function_are_checked(self, repo: RepoFactory) -> None:
        source = (
            "class C:\n"
            "    async def m(self, c):\n"
            "        if c:\n"
            '            return {"a": 1}\n'
            '        return {"b": 1}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::C.m", _shapes("{a}", "{b}"))]

    def test_returns_inside_blocks_are_seen(self, repo: RepoFactory) -> None:
        source = (
            "def f(xs):\n"
            "    for x in xs:\n"
            "        try:\n"
            "            with x:\n"
            '                return {"a": 1}\n'
            "        except E:\n"
            '            return {"b": 1}\n'
            "    match xs:\n"
            "        case []:\n"
            '            return {"a": 2}\n'
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _shapes("{a}", "{b}"))]


class TestFileSet:
    def test_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": TWO_SHAPES})
        assert _run(root, _policy()) == []

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"a/m.py": TWO_SHAPES, "b/m.py": TWO_SHAPES})
        assert _run(root, _policy(include=("a/**",))) == [
            Finding("a/m.py::f", _shapes("{a, b}", "{a}"))
        ]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f(:\n", "n.py": TWO_SHAPES})
        assert _run(root, _policy()) == [Finding("n.py::f", _shapes("{a, b}", "{a}"))]


class TestExemptions:
    def test_exempt_function_passes(self, repo: RepoFactory) -> None:
        root = repo({"m.py": TWO_SHAPES})
        assert _run(root, _policy(exempt={"m.py::f": "two message kinds"})) == []

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "x = 1\n"})
        policy = _policy(exempt={"gone.py::f": "r"})
        assert _run(root, policy) == [_stale("gone.py::f", "names no file")]

    def test_entry_naming_a_test_path_names_no_file(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": TWO_SHAPES})
        policy = _policy(exempt={"tests/test_m.py::f": "r"})
        assert _run(root, policy) == [_stale("tests/test_m.py::f", "names no file")]

    def test_entry_naming_no_function_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": TWO_SHAPES})
        policy = _policy(exempt={"m.py::g": "r"})
        assert _run(root, policy) == [
            Finding("m.py::f", _shapes("{a, b}", "{a}")),
            _stale("m.py::g", "names no function"),
        ]

    def test_entry_on_one_shape_function_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": 'def f():\n    return {"a": 1}\n'})
        policy = _policy(exempt={"m.py::f": "r"})
        assert _run(root, policy) == [
            _stale("m.py::f", "returns one shape, so it needs no exemption")
        ]

    def test_entry_covers_every_function_its_key_names(self, repo: RepoFactory) -> None:
        source = TWO_SHAPES + 'def f():\n    return {"a": 1}\n'
        root = repo({"m.py": source})
        assert _run(root, _policy(exempt={"m.py::f": "r"})) == []


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({"m.py": TWO_SHAPES})
    policy = _policy()
    state = State()
    assert ReturnsGate().accept(build_tree(root, policy), policy, state) is state
