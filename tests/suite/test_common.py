"""Tests for filepawl.gates.suite.common: own code and imports (design.md §6.12)."""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import default_policy, load_policy
from filepawl.errors import ConfigError
from filepawl.gates.suite.common import Imports, is_own_dotted, own_names, read_imports
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

TREE = {
    "pkg/__init__.py": "",
    "pkg/m.py": "x = 1\n",
    "tool.py": "",
    "src/lib/b.py": "",
    "tests/test_x.py": "",
    "tests/helper.py": "",
}


def _own(root: Path, packages: tuple[str, ...] | None) -> frozenset[str]:
    policy = dataclasses.replace(default_policy(), packages=packages)
    return own_names(build_tree(root, policy), policy)


def test_own_names_come_from_non_test_files_with_src_dropped(
    repo: RepoFactory,
) -> None:
    assert _own(repo(TREE), None) == {"pkg", "tool", "lib"}


def test_packages_replaces_the_derived_names(repo: RepoFactory) -> None:
    root = repo(TREE)
    assert (_own(root, ("other",)), _own(root, ())) == ({"other"}, frozenset())


def test_packages_is_read_from_policy(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.filepawl]\npackages = ["a", "b"]\n', encoding="utf-8"
    )
    assert (load_policy(tmp_path).packages, default_policy().packages) == (
        ("a", "b"),
        None,
    )


def test_packages_must_be_a_list_of_strings(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.filepawl]\npackages = "a"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="packages must be a list of strings"):
        load_policy(tmp_path)


SOURCE = """\
import os
from os import getcwd
import os.path as osp
from pathlib import Path
import pkg.m
import pkg.m as a
from pkg.m import x as y
from . import z
from pkgx import w
"""


def _imports() -> Imports:
    return read_imports(ast.parse(SOURCE), frozenset({"pkg"}))


def _expr(text: str) -> ast.expr:
    return ast.parse(text, mode="eval").body


def test_own_bindings_are_names_imports_bind_to_own_code() -> None:
    assert _imports().own == {"pkg", "a", "y"}


@pytest.mark.parametrize(
    ("text", "dotted"),
    [
        ("getcwd", "os.getcwd"),
        ("os.getcwd", "os.getcwd"),
        ("osp.expanduser", "os.path.expanduser"),
        ("Path.cwd", "pathlib.Path.cwd"),
        ("a.f", "pkg.m.f"),
        ("foo.bar", "foo.bar"),
        ("f().bar", None),
    ],
)
def test_dotted_names_resolve_through_imports(text: str, dotted: str | None) -> None:
    assert _imports().dotted(_expr(text)) == dotted


@pytest.mark.parametrize(
    ("text", "own"),
    [("a.b.c", True), ("y", True), ("z.q", False), ("w.q", False), ("os", False)],
)
def test_own_rooted_expressions_start_at_an_own_binding(text: str, own: bool) -> None:
    assert _imports().own_rooted(_expr(text)) is own


@pytest.mark.parametrize(
    ("text", "own"), [("pkg.m.f", True), ("pkg", True), ("pkgx.m", False)]
)
def test_own_dotted_strings_start_with_an_own_name(text: str, own: bool) -> None:
    assert is_own_dotted(text, frozenset({"pkg"})) is own
