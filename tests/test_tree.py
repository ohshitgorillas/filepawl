"""Tests for filepawl.tree: glob matching and the git-backed tree scan."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from filepawl.errors import ConfigError
from filepawl.tree import Tree, build_tree, find_root, glob_match

if TYPE_CHECKING:
    from filepawl.config import Policy

try:
    from filepawl.config import LanguagePolicy as _LanguagePolicy
    from filepawl.config import Policy as _ConcretePolicy
    from filepawl.config import default_policy as _default_policy

    def _make_policy(
        tests: tuple[str, ...] = ("tests/**",),
        languages: dict[str, _LanguagePolicy] | None = None,
    ) -> Policy:
        base = _default_policy()
        if languages is None:
            languages = dict(base.languages)
        return _ConcretePolicy(
            languages=languages,
            tests=tests,
            length=base.length,
            dircount=base.dircount,
            exempt=base.exempt,
            gate_tables=base.gate_tables,
        )

except ImportError:  # filepawl.config not yet present

    @dataclass(frozen=True)
    class _LanguagePolicy:  # type: ignore[no-redef]
        include: tuple[str, ...]

    @dataclass(frozen=True)
    class _Policy:
        tests: tuple[str, ...] = ("tests/**",)
        languages: dict[str, _LanguagePolicy] = field(
            default_factory=lambda: {"python": _LanguagePolicy(include=("**/*.py",))}
        )

    def _make_policy(
        tests: tuple[str, ...] = ("tests/**",),
        languages: dict[str, _LanguagePolicy] | None = None,
    ) -> Policy:
        if languages is None:
            languages = {"python": _LanguagePolicy(include=("**/*.py",))}
        policy = _Policy(tests=tests, languages=languages)
        return policy  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# glob_match


@pytest.mark.parametrize(
    "path",
    ["a.py", "x/a.py", ".claude/hooks/a.py"],
)
def test_glob_match_double_star_prefix(path: str) -> None:
    assert glob_match("**/*.py", path)


@pytest.mark.parametrize(
    "path",
    ["tests/a.py", "tests/x/y.py"],
)
def test_glob_match_double_star_suffix(path: str) -> None:
    assert glob_match("tests/**", path)


def test_glob_match_double_star_suffix_does_not_match_sibling_prefix() -> None:
    assert not glob_match("tests/**", "testsx/a.py")


def test_glob_match_star_does_not_cross_slash() -> None:
    assert not glob_match("*.py", "x/a.py")
    assert glob_match("*.py", "a.py")


def test_glob_match_no_match_wrong_extension() -> None:
    assert not glob_match("**/*.py", "a.txt")


# ---------------------------------------------------------------------------
# Tree.is_test / language_of / line_count / measured


def test_is_test_uses_tests_globs() -> None:
    policy = _make_policy()
    tree = Tree(
        root=Path("/tmp"),
        files=(),
        selected=None,
        tests=policy.tests,
        languages={},
    )
    assert tree.is_test("tests/a.py")
    assert tree.is_test("tests/x/y.py")
    assert not tree.is_test("filepawl/tree.py")


def test_language_of_returns_first_matching_block() -> None:
    tree = Tree(
        root=Path("/tmp"),
        files=(),
        selected=None,
        tests=(),
        languages={
            "python": ("**/*.py",),
            "javascript": ("**/*.js", "**/*.css"),
        },
    )
    assert tree.language_of("a.py") == "python"
    assert tree.language_of("a.js") == "javascript"
    assert tree.language_of("a.css") == "javascript"
    assert tree.language_of("a.txt") is None


def test_language_of_first_block_wins_on_overlap() -> None:
    tree = Tree(
        root=Path("/tmp"),
        files=(),
        selected=None,
        tests=(),
        languages={
            "first": ("**/*.py",),
            "second": ("**/*.py",),
        },
    )
    assert tree.language_of("a.py") == "first"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("a\nb\nc\n", 3),
        ("a\nb\nc", 3),
        ("a\r\nb\r\n", 2),
    ],
)
def test_line_count(
    repo: Callable[[dict[str, str | int]], Path], content: str, expected: int
) -> None:
    root = repo({"a.py": content})
    tree = Tree(
        root=root,
        files=("a.py",),
        selected=None,
        tests=(),
        languages={},
    )
    assert tree.line_count("a.py") == expected


def test_measured_returns_selected_when_narrowed() -> None:
    tree = Tree(
        root=Path("/tmp"),
        files=("a.py", "b.py"),
        selected=("a.py",),
        tests=(),
        languages={},
    )
    assert tree.measured() == ("a.py",)


def test_measured_returns_files_when_whole_tree() -> None:
    tree = Tree(
        root=Path("/tmp"),
        files=("a.py", "b.py"),
        selected=None,
        tests=(),
        languages={},
    )
    assert tree.measured() == ("a.py", "b.py")


# ---------------------------------------------------------------------------
# find_root


def test_find_root_returns_toplevel(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1})
    assert find_root(root) == root.resolve()


def test_find_root_raises_config_error_outside_git(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    with pytest.raises(ConfigError):
        find_root(outside)


# ---------------------------------------------------------------------------
# build_tree


def test_build_tree_filters_by_include_globs(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo(
        {
            "a.py": 3,
            "x/a.py": 2,
            "README.md": "hi\n",
            "tests/test_a.py": 5,
        }
    )
    tree = build_tree(root, _make_policy())
    assert tree.files == ("a.py", "tests/test_a.py", "x/a.py")


def test_build_tree_excludes_untracked_files(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 3})
    (root / "untracked.py").write_text("x\n", encoding="utf-8")
    tree = build_tree(root, _make_policy())
    assert tree.files == ("a.py",)


def test_build_tree_excludes_tracked_files_missing_from_disk(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    """`git ls-files` still lists a tracked file deleted without `git rm`."""
    root = repo({"a.py": 3, "gone.py": 3})
    (root / "gone.py").unlink()
    tree = build_tree(root, _make_policy())
    assert tree.files == ("a.py",)


def test_build_tree_files_are_posix_relative_and_sorted(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"z.py": 1, "a.py": 1, "sub/b.py": 1})
    tree = build_tree(root, _make_policy())
    assert tree.files == ("a.py", "sub/b.py", "z.py")
    assert all("\\" not in f for f in tree.files)


def test_build_tree_no_paths_is_whole_tree(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1, "b.py": 1})
    tree = build_tree(root, _make_policy())
    assert tree.selected is None
    assert tree.measured() == tree.files


def test_build_tree_selected_keeps_only_argv_files(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1, "b.py": 1})
    tree = build_tree(root, _make_policy(), paths=["a.py"])
    assert tree.selected == ("a.py",)
    assert tree.measured() == ("a.py",)


def test_build_tree_selected_directory_selects_everything_beneath(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1, "sub/b.py": 1, "sub/c.py": 1, "other/d.py": 1})
    tree = build_tree(root, _make_policy(), paths=["sub"])
    assert tree.selected == ("sub/b.py", "sub/c.py")


def test_build_tree_selected_ignores_paths_not_in_files(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1, "README.md": "hi\n"})
    tree = build_tree(root, _make_policy(), paths=["README.md", "nope.py"])
    assert tree.selected == ()


def test_build_tree_languages_carries_include_globs(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1})
    policy = _make_policy(
        languages={
            "python": _LanguagePolicy(include=("**/*.py",)),
            "javascript": _LanguagePolicy(include=("**/*.js",)),
        }
    )
    tree = build_tree(root, policy)
    assert tree.languages == {
        "python": ("**/*.py",),
        "javascript": ("**/*.js",),
    }


def test_build_tree_tests_globs_carried_from_policy(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 1, "tests/test_a.py": 1})
    tree = build_tree(root, _make_policy(tests=("tests/**",)))
    assert tree.is_test("tests/test_a.py")
    assert not tree.is_test("a.py")


def test_build_tree_raises_config_error_on_non_utf8_filename(tmp_path: Path) -> None:
    bad_name = b"bad\xff.py"
    try:
        decoded_name = os.fsdecode(bad_name)
    except UnicodeDecodeError:
        pytest.skip("platform filesystem encoding cannot represent the name")

    bad_path = tmp_path / decoded_name
    try:
        bad_path.write_bytes(b"x = 1\n")
    except OSError:
        pytest.skip("filesystem refused the non-UTF-8 filename")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=filepawl tests",
            "-c",
            "user.email=filepawl-tests@example.invalid",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        cwd=tmp_path,
        check=True,
    )

    with pytest.raises(ConfigError) as excinfo:
        build_tree(tmp_path, _make_policy())
    assert repr(bad_name) in str(excinfo.value)
