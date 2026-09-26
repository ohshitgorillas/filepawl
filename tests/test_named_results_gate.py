"""Tests for filepawl.gates.named_results: the named-results gate (design.md §6.9)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import NamedResultsPolicy, Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.named_results import NamedResultsGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

LOOSE = "def f() -> dict[str, Any]: ...\n"


def _returns(annotation: str) -> str:
    return f"returns an unnamed mapping ({annotation}) — name its shape"


def _aliases(value: str) -> str:
    return f"aliases an unnamed mapping ({value}) — name its shape"


def _policy(**named_results: object) -> Policy:
    return dataclasses.replace(
        default_policy(),
        named_results=NamedResultsPolicy(**named_results),  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return NamedResultsGate().run(build_tree(root, policy), policy, State())


class TestAnnotations:
    @pytest.mark.parametrize(
        "annotation",
        [
            "dict",
            "Dict",
            "Mapping",
            "MutableMapping",
            "typing.Dict",
            "collections.abc.Mapping",
            "dict[str, Any]",
            "dict[str, object]",
            "Dict[str, Any]",
            "Mapping[str, typing.Any]",
            "MutableMapping[str, object]",
            "t.Dict[str, t.Any]",
            "dict[str, Any | None]",
            "dict[str, None | object]",
            "dict[str, Optional[Any]]",
            "dict[str, Union[int, object]]",
            "dict[str, int | Optional[Any]]",
            "dict[str, Any] | None",
            "Optional[dict[str, Any]]",
            "Union[int, Mapping[str, object]]",
            "list[Mapping[str, object]]",
            "tuple[int, dict[str, Any]]",
            "Callable[[dict[str, Any]], int]",
            "dict[str, dict[str, Any]]",
            "type[dict]",
            "'dict[str, Any]'",
            "list['Mapping[str, Any]']",
            "dict[str, 'Any']",
        ],
    )
    def test_loose_annotation_fails(self, repo: RepoFactory, annotation: str) -> None:
        root = repo({"m.py": f"def f() -> {annotation}: ...\n"})
        assert _run(root, _policy()) == [Finding("m.py::f", _returns(annotation))]

    @pytest.mark.parametrize(
        "annotation",
        [
            "dict[str, int]",
            "Mapping[str, str | None]",
            "dict[str, list[Any]]",
            "dict[str, Callable[..., Any]]",
            "Any",
            "object",
            "list[Any]",
            "None",
            "Literal['dict', 'Mapping']",
            "'not ( an annotation'",
            "dict[str, JsonValue]",
        ],
    )
    def test_named_annotation_passes(self, repo: RepoFactory, annotation: str) -> None:
        root = repo({"m.py": f"def f() -> {annotation}: ...\n"})
        assert _run(root, _policy()) == []

    def test_unannotated_function_passes(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f(x: dict[str, Any]):\n    return x\n"})
        assert _run(root, _policy()) == []


class TestFunctions:
    def test_async_function_is_checked(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "async def f() -> dict: ...\n"})
        assert _run(root, _policy()) == [Finding("m.py::f", _returns("dict"))]

    def test_nested_function_and_method_named_by_qualified_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "class C:\n"
            "    class D:\n"
            "        def m(self) -> dict: ...\n"
            "def outer() -> int:\n"
            "    if True:\n"
            "        def inner() -> Mapping[str, object]: ...\n"
            "    return 1\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [
            Finding("m.py::C.D.m", _returns("dict")),
            Finding("m.py::outer.inner", _returns("Mapping[str, object]")),
        ]


class TestAliases:
    @pytest.mark.parametrize(
        ("source", "value"),
        [
            ("Wire = dict[str, Any]\n", "dict[str, Any]"),
            ("Wire = dict\n", "dict"),
            ("Wire = typing.Mapping\n", "typing.Mapping"),
            (
                "Wire = Optional[Mapping[str, object]]\n",
                "Optional[Mapping[str, object]]",
            ),
            ("Wire = dict[str, Any] | None\n", "dict[str, Any] | None"),
            (
                "Wire = Callable[[str, dict[str, Any]], int]\n",
                "Callable[[str, dict[str, Any]], int]",
            ),
            ("Wire: TypeAlias = dict[str, Any]\n", "dict[str, Any]"),
            ("Wire: typing.TypeAlias = 'dict[str, Any]'\n", "'dict[str, Any]'"),
            ("type Wire = dict[str, Any]\n", "dict[str, Any]"),
            ("if TYPE_CHECKING:\n    Wire = dict[str, Any]\n", "dict[str, Any]"),
            (
                "try:\n    pass\nexcept ImportError:\n    Wire = dict[str, Any]\n",
                "dict[str, Any]",
            ),
        ],
    )
    def test_loose_module_level_alias_fails(
        self, repo: RepoFactory, source: str, value: str
    ) -> None:
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::Wire", _aliases(value))]

    def test_every_plain_name_target_is_an_alias(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "A = B = dict[str, Any]\n"})
        assert _run(root, _policy()) == [
            Finding("m.py::A", _aliases("dict[str, Any]")),
            Finding("m.py::B", _aliases("dict[str, Any]")),
        ]

    @pytest.mark.parametrize(
        "source",
        [
            "Row = dict[str, int]\n",
            "x = dict(a=1)\n",
            "NAME = 'dict[str, Any]'\n",
            "x: dict[str, Any] = {}\n",
            "class C:\n    Wire = dict[str, Any]\n",
            "def f() -> None:\n    Wire = dict[str, Any]\n",
            "JsonValue = (\n"
            "    str | int | float | bool | None"
            " | list['JsonValue'] | dict[str, 'JsonValue']\n"
            ")\n",
        ],
    )
    def test_other_assignments_pass(self, repo: RepoFactory, source: str) -> None:
        root = repo({"m.py": source})
        assert _run(root, _policy()) == []


class TestFileSet:
    def test_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": LOOSE})
        assert _run(root, _policy()) == []

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"a/m.py": LOOSE, "b/m.py": LOOSE})
        assert _run(root, _policy(include=("a/**",))) == [
            Finding("a/m.py::f", _returns("dict[str, Any]"))
        ]

    def test_excluded_files_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"a/m.py": LOOSE, "b/wire/m.py": LOOSE})
        assert _run(root, _policy(exclude=("b/wire/**",))) == [
            Finding("a/m.py::f", _returns("dict[str, Any]"))
        ]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f(:\n", "n.py": LOOSE})
        assert _run(root, _policy()) == [Finding("n.py::f", _returns("dict[str, Any]"))]


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({"m.py": LOOSE})
    policy = _policy()
    state = State()
    assert NamedResultsGate().accept(build_tree(root, policy), policy, state) is state
