"""Tests for filepawl.gates.nesting: the nesting gate (design.md §6.7)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import NestingPolicy, Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import NestingGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

#: Each block opener with the indent its body sits at past the opener, and the
#: lines that close it. A ``case`` arm puts ``match``'s body two indents in.
BLOCKS: dict[str, tuple[list[str], int, list[str]]] = {
    "if": (["if c:"], 1, []),
    "for": (["for i in x:"], 1, []),
    "async for": (["async for i in x:"], 1, []),
    "while": (["while c:"], 1, []),
    "with": (["with c:"], 1, []),
    "async with": (["async with c:"], 1, []),
    "try": (["try:"], 1, ["except E:", "    pass"]),
    "try star": (["try:"], 1, ["except* E:", "    pass"]),
    "match": (["match v:", "    case _:"], 2, []),
}


def _nest(kind: str, depth: int, indent: int = 1) -> list[str]:
    opener, step, trailer = BLOCKS[kind]
    pad = "    " * indent
    lines = [pad + line for line in opener]
    if depth > 1:
        lines += _nest(kind, depth - 1, indent + step)
    else:
        lines.append("    " * (indent + step) + "pass")
    return lines + [pad + line for line in trailer]


def _function(kind: str, depth: int, name: str = "f") -> str:
    head = "async def" if kind.startswith("async") else "def"
    return "\n".join([f"{head} {name}():", *_nest(kind, depth)]) + "\n"


def _deep(depth: int, limit: int = 4) -> str:
    return f"nests {depth} deep (max {limit}) — flatten the function"


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.nesting.exempt] {key!r}: {message}"
    )


def _policy(**nesting: object) -> Policy:
    return dataclasses.replace(
        default_policy(), nesting=NestingPolicy(**nesting)  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return NestingGate().run(build_tree(root, policy), policy, State())


class TestDepth:
    @pytest.mark.parametrize("kind", sorted(BLOCKS))
    def test_each_block_at_the_limit_passes(self, repo: RepoFactory, kind: str) -> None:
        root = repo({"m.py": _function(kind, 4)})
        at_limit = _run(root, _policy())
        under_limit = _run(root, _policy(max_depth=3))
        assert (at_limit, under_limit) == ([], [Finding("m.py::f", _deep(4, 3))])

    @pytest.mark.parametrize("kind", sorted(BLOCKS))
    def test_each_block_past_the_limit_fails(
        self, repo: RepoFactory, kind: str
    ) -> None:
        root = repo({"m.py": _function(kind, 5)})
        assert _run(root, _policy()) == [Finding("m.py::f", _deep(5))]

    def test_straight_line_function_passes(self, repo: RepoFactory) -> None:
        root = repo(
            {
                "m.py": "def f():\n    return 1\n",
                "n.py": "def f():\n    if c:\n        pass\n",
            }
        )
        assert _run(root, _policy(max_depth=0)) == [Finding("n.py::f", _deep(1, 0))]

    def test_one_block_is_one_deep(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f():\n    if c:\n        pass\n"})
        assert _run(root, _policy(max_depth=0)) == [Finding("m.py::f", _deep(1, 0))]

    def test_elif_chain_shares_its_ifs_level(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    if a:\n"
            "        pass\n"
            "    elif b:\n"
            "        pass\n"
            "    elif c:\n"
            "        pass\n"
            "    else:\n"
            "        pass\n"
        )
        root = repo({"m.py": source})
        at_one = _run(root, _policy(max_depth=1))
        at_zero = _run(root, _policy(max_depth=0))
        assert (at_one, at_zero) == ([], [Finding("m.py::f", _deep(1, 0))])

    def test_if_inside_plain_else_is_a_level(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    if a:\n"
            "        pass\n"
            "    else:\n"
            "        if b:\n"
            "            pass\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy(max_depth=1)) == [Finding("m.py::f", _deep(2, 1))]

    @pytest.mark.parametrize(
        "opener",
        [
            ["try:", "    pass", "except E:"],
            ["try:", "    pass", "finally:"],
            ["for i in x:", "    pass", "else:"],
            ["while c:", "    pass", "else:"],
        ],
        ids=["except", "finally", "for-else", "while-else"],
    )
    def test_every_branch_of_a_block_is_inside_it(
        self, repo: RepoFactory, opener: list[str]
    ) -> None:
        lines = ["def f():", *("    " + line for line in opener), *_nest("if", 1, 2)]
        root = repo({"m.py": "\n".join(lines) + "\n"})
        assert _run(root, _policy(max_depth=1)) == [Finding("m.py::f", _deep(2, 1))]

    def test_deepest_branch_counts(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    if a:\n"
            "        pass\n"
            "    for i in x:\n"
            "        while c:\n"
            "            pass\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy(max_depth=1)) == [Finding("m.py::f", _deep(2, 1))]


class TestNaming:
    def test_nested_def_starts_its_own_count(self, repo: RepoFactory) -> None:
        source = (
            "def outer():\n"
            "    if c:\n"
            "        def inner():\n"
            "            if c:\n"
            "                pass\n"
        )
        root = repo({"m.py": source})
        at_one = _run(root, _policy(max_depth=1))
        at_zero = _run(root, _policy(max_depth=0))
        assert (at_one, at_zero) == (
            [],
            [
                Finding("m.py::outer", _deep(1, 0)),
                Finding("m.py::outer.inner", _deep(1, 0)),
            ],
        )

    def test_nested_def_is_reported_under_its_dotted_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def outer():\n"
            "    def inner():\n"
            "        if a:\n"
            "            if b:\n"
            "                pass\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy(max_depth=1)) == [
            Finding("m.py::outer.inner", _deep(2, 1))
        ]

    def test_method_is_reported_under_its_class(self, repo: RepoFactory) -> None:
        source = (
            "class C:\n"
            "    class D:\n"
            "        def m(self):\n"
            "            if a:\n"
            "                if b:\n"
            "                    pass\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy(max_depth=1)) == [Finding("m.py::C.D.m", _deep(2, 1))]

    def test_function_under_module_level_block_starts_at_zero(
        self, repo: RepoFactory
    ) -> None:
        source = "if c:\n    def f():\n        if a:\n            pass\n"
        root = repo({"m.py": source})
        at_one = _run(root, _policy(max_depth=1))
        at_zero = _run(root, _policy(max_depth=0))
        assert (at_one, at_zero) == ([], [Finding("m.py::f", _deep(1, 0))])

    def test_module_level_nesting_is_not_measured(self, repo: RepoFactory) -> None:
        source = "if a:\n    if b:\n        if c:\n            pass\n"
        function = "def g():\n    if a:\n        pass\n"
        root = repo({"m.py": source + function})
        assert _run(root, _policy(max_depth=0)) == [Finding("m.py::g", _deep(1, 0))]


class TestFileSet:
    def test_test_paths_are_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": _function("if", 5, "test_f")})
        assert _run(root, _policy()) == [Finding("tests/test_m.py::test_f", _deep(5))]

    def test_include_narrows_the_checked_files(self, repo: RepoFactory) -> None:
        root = repo({"pkg/a.py": _function("if", 5), "tools/b.py": _function("if", 5)})
        assert _run(root, _policy(include=("pkg/**",))) == [
            Finding("pkg/a.py::f", _deep(5))
        ]

    def test_unparseable_file_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"bad.py": "def f(:\n", "ok.py": _function("if", 5)})
        assert _run(root, _policy()) == [Finding("ok.py::f", _deep(5))]

    def test_non_python_files_are_not_parsed(self, repo: RepoFactory) -> None:
        root = repo({"notes.txt": "if a:\n", "ok.py": _function("if", 5)})
        assert _run(root, _policy()) == [Finding("ok.py::f", _deep(5))]

    def test_findings_are_sorted(self, repo: RepoFactory) -> None:
        root = repo({"b.py": _function("if", 5), "a.py": _function("if", 5, "g")})
        assert _run(root, _policy()) == [
            Finding("a.py::g", _deep(5)),
            Finding("b.py::f", _deep(5)),
        ]


class TestExemptions:
    def test_exempt_function_passes(self, repo: RepoFactory) -> None:
        root = repo({"m.py": _function("if", 5)})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={"m.py::f": "state machine"}))
        assert (plain, exempt) == ([Finding("m.py::f", _deep(5))], [])

    def test_exemption_names_one_function_only(self, repo: RepoFactory) -> None:
        root = repo({"m.py": _function("if", 5) + _function("if", 5, "g")})
        assert _run(root, _policy(exempt={"m.py::f": "state machine"})) == [
            Finding("m.py::g", _deep(5))
        ]

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "x = 1\n"})
        assert _run(root, _policy(exempt={"gone.py::f": "old"})) == [
            _stale("gone.py::f", "names no file")
        ]

    def test_entry_outside_include_names_no_file(self, repo: RepoFactory) -> None:
        root = repo({"tools/m.py": _function("if", 5)})
        policy = _policy(include=("pkg/**",), exempt={"tools/m.py::f": "old"})
        assert _run(root, policy) == [_stale("tools/m.py::f", "names no file")]

    def test_entry_naming_no_function_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": _function("if", 1)})
        assert _run(root, _policy(exempt={"m.py::g": "old"})) == [
            _stale("m.py::g", "names no function")
        ]

    def test_entry_within_the_limit_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": _function("if", 3)})
        assert _run(root, _policy(exempt={"m.py::f": "old"})) == [
            _stale("m.py::f", "nests 3 deep, within the limit of 4")
        ]

    def test_entry_covering_a_deep_same_named_function_stands(
        self, repo: RepoFactory
    ) -> None:
        lines = [
            "class C:",
            "    @property",
            "    def v(self):",
            *_nest("if", 5, 2),
            "    @v.setter",
            "    def v(self, x):",
            "        pass",
        ]
        root = repo({"m.py": "\n".join(lines) + "\n"})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={"m.py::C.v": "property parser"}))
        assert (plain, exempt) == ([Finding("m.py::C.v", _deep(5))], [])


def test_limit_is_policy(repo: RepoFactory) -> None:
    root = repo({"m.py": _function("if", 3)})
    assert _run(root, _policy(max_depth=2)) == [Finding("m.py::f", _deep(3, 2))]


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({"m.py": _function("if", 5)})
    policy = _policy()
    state = State()
    assert NestingGate().accept(build_tree(root, policy), policy, state) is state
