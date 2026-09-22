"""Shared fixtures for filepawl tests."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _write_file(path: Path, content: str | int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, int):
        text = "".join(f"line {n}\n" for n in range(1, content + 1))
    else:
        text = content
    path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Callable[[dict[str, str | int]], Path]:
    """Build a synthetic git repository from a {path: content} mapping.

    An int value writes that many lines as "line N\\n"; a str value is
    written verbatim. Parent directories are created as needed. The tree
    is committed with a fixed author so runs are deterministic.
    """

    def make(files: dict[str, str | int]) -> Path:
        root = tmp_path
        for rel, content in files.items():
            _write_file(root / rel, content)

        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(
            root,
            "-c",
            "user.name=filepawl tests",
            "-c",
            "user.email=filepawl-tests@example.invalid",
            "commit",
            "-q",
            "-m",
            "init",
        )
        return root

    return make
