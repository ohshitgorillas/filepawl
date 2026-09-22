"""Tests for filepawl.gates.dircount: the directory-count gate (design.md §6.2)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import default_policy
from filepawl.gates.base import Finding
from filepawl.gates.dircount import DircountGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]


def _tree(root: Path, policy: object) -> object:
    return build_tree(root, policy)  # type: ignore[arg-type]


class TestDircountGate:
    def test_name(self) -> None:
        assert DircountGate().name == "dircount"

    def test_at_cap_passes(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(
            default_policy(),
            dircount=dataclasses.replace(default_policy().dircount, cap=3),
        )
        files = {f"pkg/f{n}.py": 1 for n in range(3)}
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == []

    def test_over_cap_fails_naming_directory_and_count(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(
            default_policy(),
            dircount=dataclasses.replace(default_policy().dircount, cap=3),
        )
        files = {f"pkg/f{n}.py": 1 for n in range(4)}
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == [Finding(path="pkg", message="4 files, cap 3")]

    def test_init_py_excluded(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(
            default_policy(),
            dircount=dataclasses.replace(default_policy().dircount, cap=3),
        )
        files = {f"pkg/f{n}.py": 1 for n in range(3)}
        files["pkg/__init__.py"] = 1
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == []

    def test_nested_directories_counted_separately(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(
            default_policy(),
            dircount=dataclasses.replace(default_policy().dircount, cap=1),
        )
        files = {
            "pkg/a.py": 1,
            "pkg/sub/b.py": 1,
            "pkg/sub/c.py": 1,
        }
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == [Finding(path="pkg/sub", message="2 files, cap 1")]

    def test_tests_cap_applied_to_tests_directory(self, repo: RepoFactory) -> None:
        base = default_policy()
        policy = dataclasses.replace(
            base,
            dircount=dataclasses.replace(base.dircount, cap=1, cap_tests=3),
        )
        files = {f"tests/sub/test_{n}.py": 1 for n in range(3)}
        files["pkg/a.py"] = 1
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == []

    def test_bare_tests_directory_passes_at_cap_tests(self, repo: RepoFactory) -> None:
        base = default_policy()
        policy = dataclasses.replace(
            base,
            dircount=dataclasses.replace(base.dircount, cap_tests=31),
        )
        files = {f"tests/test_{n}.py": 1 for n in range(31)}
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == []

    def test_bare_tests_directory_fails_over_cap_tests(self, repo: RepoFactory) -> None:
        base = default_policy()
        policy = dataclasses.replace(
            base,
            dircount=dataclasses.replace(base.dircount, cap_tests=30),
        )
        files = {f"tests/test_{n}.py": 1 for n in range(31)}
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == [Finding(path="tests", message="31 files, cap 30")]

    def test_mixed_directory_uses_cap_tests_when_any_file_is_a_test(
        self, repo: RepoFactory
    ) -> None:
        base = default_policy()
        policy = dataclasses.replace(
            base,
            tests=("tests/test_*.py",),
            dircount=dataclasses.replace(base.dircount, cap=1, cap_tests=5),
        )
        files = {
            "tests/test_a.py": 1,
            "tests/conftest.py": 1,
        }
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == []

    def test_root_directory_counted(self, repo: RepoFactory) -> None:
        policy = dataclasses.replace(
            default_policy(),
            dircount=dataclasses.replace(default_policy().dircount, cap=1),
        )
        files = {"a.py": 1, "b.py": 1}
        root = repo(files)
        tree = build_tree(root, policy)

        findings = DircountGate().run(tree, policy, State())

        assert findings == [Finding(path=".", message="2 files, cap 1")]

    def test_accept_returns_state_unchanged(self, repo: RepoFactory) -> None:
        policy = default_policy()
        files = {"pkg/a.py": 1}
        root = repo(files)
        tree = build_tree(root, policy)
        state = State()

        assert DircountGate().accept(tree, policy, state) is state
