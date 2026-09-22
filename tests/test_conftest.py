"""Prove the `repo` fixture builds a real git checkout as documented."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def test_repo_runs_git_init(repo: Callable[[dict[str, str | int]], Path]) -> None:
    root = repo({"a.py": 10})
    assert (root / ".git").is_dir()


def test_repo_stages_files(repo: Callable[[dict[str, str | int]], Path]) -> None:
    root = repo({"a.py": 10, "tests/t.py": "x\n"})
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = set(result.stdout.split())
    assert tracked == {"a.py", "tests/t.py"}

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_repo_writes_int_as_that_many_lines(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"a.py": 10, "b.py": 3})
    assert (root / "a.py").read_text(encoding="utf-8").splitlines() == [
        f"line {n}" for n in range(1, 11)
    ]
    assert (root / "b.py").read_text(encoding="utf-8").splitlines() == [
        "line 1",
        "line 2",
        "line 3",
    ]


def test_repo_writes_string_content_verbatim(
    repo: Callable[[dict[str, str | int]], Path],
) -> None:
    root = repo({"tests/t.py": "x\n"})
    assert (root / "tests" / "t.py").read_text(encoding="utf-8") == "x\n"
