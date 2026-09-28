"""Judge cases: silenced findings between two trees (docs/design.md §7.2)."""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Callable
from pathlib import Path

from filepawl.config import JudgePolicy, Policy, default_policy
from filepawl.config_code import HandlersPolicy, ReturnsPolicy
from filepawl.judge.cases import Case, find_cases

Repo = Callable[[dict[str, str | int]], Path]

HANDLER_RETURN = (
    "def load(path):\n"
    "    try:\n"
    "        return read(path)\n"
    "    except OSError:\n"
    "        return None\n"
)
HANDLER_MOVED = (
    "def load(path):\n"
    "    result = None\n"
    "    try:\n"
    "        result = read(path)\n"
    "    except OSError:\n"
    "        pass\n"
    "    return result\n"
)
TWO_SHAPES = (
    "def info(ok):\n" "    if ok:\n" '        return {"a": 1}\n' '    return {"b": 2}\n'
)
TWO_SHAPES_BUILT = (
    "def info(ok):\n"
    "    if ok:\n"
    '        return {"a": 1}\n'
    "    return dict(b=2)\n"
)
KEEP = "def keep():\n    return 1\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _stage(root: Path, files: dict[str, str | None]) -> None:
    """Write (or, for None, delete) each file and stage the result."""
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")


def _commit(root: Path) -> None:
    _git(
        root,
        "-c",
        "user.name=filepawl tests",
        "-c",
        "user.email=filepawl-tests@example.invalid",
        "commit",
        "-q",
        "-m",
        "change",
    )


def _policy(**changes: object) -> Policy:
    return dataclasses.replace(default_policy(), **changes)  # type: ignore[arg-type]


def _keys(cases: list[Case]) -> list[tuple[str, str]]:
    return [(case.gate, case.key) for case in cases]


def test_a_handlers_finding_silenced_in_place_makes_a_case(repo: Repo) -> None:
    root = repo({"pkg/io.py": KEEP + "\n\n" + HANDLER_RETURN})
    _stage(root, {"pkg/io.py": KEEP + "\n\n" + HANDLER_MOVED})
    assert find_cases(root, default_policy(), head=False) == [
        Case(
            gate="handlers",
            key="pkg/io.py::load",
            old=HANDLER_RETURN.rstrip("\n"),
            new=HANDLER_MOVED.rstrip("\n"),
            helpers=(),
        )
    ]


def test_a_returns_finding_silenced_in_place_makes_a_case(repo: Repo) -> None:
    root = repo({"pkg/info.py": TWO_SHAPES})
    _stage(root, {"pkg/info.py": TWO_SHAPES_BUILT})
    assert find_cases(root, default_policy(), head=False) == [
        Case(
            gate="returns",
            key="pkg/info.py::info",
            old=TWO_SHAPES.rstrip("\n"),
            new=TWO_SHAPES_BUILT.rstrip("\n"),
            helpers=(),
        )
    ]


def test_methods_are_keyed_by_qualified_name_with_decorators_in_the_source(
    repo: Repo,
) -> None:
    def method(body: str) -> str:
        return "class Store:\n    @staticmethod\n" + "".join(
            "    " + line + "\n" for line in body.splitlines()
        )

    root = repo({"pkg/store.py": method(HANDLER_RETURN)})
    _stage(root, {"pkg/store.py": method(HANDLER_MOVED)})
    [case] = find_cases(root, default_policy(), head=False)
    assert (
        case.key,
        case.new.startswith("    @staticmethod\n    def load(path):\n"),
    ) == ("pkg/store.py::Store.load", True)


def test_the_helpers_are_the_functions_the_new_version_adds(repo: Repo) -> None:
    helper = "def _fallback():\n    return None\n"
    old = KEEP + "\n\n" + HANDLER_RETURN
    new = (
        KEEP
        + "\n\n"
        + helper
        + "\n\n"
        + HANDLER_MOVED
        + "\n\ndef _other():\n    return 2\n"
    )
    root = repo({"pkg/io.py": old})
    _stage(root, {"pkg/io.py": new})
    [case] = find_cases(root, default_policy(), head=False)
    assert case.helpers == (
        ("_fallback", helper.rstrip("\n")),
        ("_other", "def _other():\n    return 2"),
    )


def test_a_function_that_moved_away_makes_no_case(repo: Repo) -> None:
    root = repo({"pkg/io.py": KEEP + "\n\n" + HANDLER_RETURN, "pkg/b.py": KEEP})
    _stage(root, {"pkg/io.py": KEEP, "pkg/b.py": KEEP + "\n\n" + HANDLER_MOVED})
    moved = find_cases(root, default_policy(), head=False)
    _stage(root, {"pkg/io.py": KEEP + "\n\n" + HANDLER_MOVED})
    assert (moved, _keys(find_cases(root, default_policy(), head=False))) == (
        [],
        [("handlers", "pkg/io.py::load")],
    )


def test_a_file_added_or_deleted_makes_no_case(repo: Repo) -> None:
    root = repo({"pkg/old.py": HANDLER_RETURN, "pkg/io.py": HANDLER_RETURN})
    _stage(root, {"pkg/old.py": None, "pkg/new.py": HANDLER_MOVED})
    added_and_deleted = find_cases(root, default_policy(), head=False)
    _stage(root, {"pkg/io.py": HANDLER_MOVED})
    assert (
        added_and_deleted,
        _keys(find_cases(root, default_policy(), head=False)),
    ) == (
        [],
        [("handlers", "pkg/io.py::load")],
    )


def test_a_finding_that_persists_makes_no_case(repo: Repo) -> None:
    root = repo({"pkg/io.py": HANDLER_RETURN})
    _stage(root, {"pkg/io.py": HANDLER_RETURN + "\n\n" + KEEP})
    persisting = find_cases(root, default_policy(), head=False)
    _stage(root, {"pkg/io.py": HANDLER_MOVED + "\n\n" + KEEP})
    assert (persisting, _keys(find_cases(root, default_policy(), head=False))) == (
        [],
        [("handlers", "pkg/io.py::load")],
    )


def test_an_exempt_key_makes_no_case(repo: Repo) -> None:
    root = repo({"pkg/io.py": HANDLER_RETURN, "pkg/info.py": TWO_SHAPES})
    _stage(root, {"pkg/io.py": HANDLER_MOVED, "pkg/info.py": TWO_SHAPES_BUILT})
    judge = JudgePolicy(exempt={"pkg/io.py::load": "the spec requires silence"})
    assert _keys(find_cases(root, _policy(judge=judge), head=False)) == [
        ("returns", "pkg/info.py::info")
    ]


def test_a_disabled_gate_makes_no_case(repo: Repo) -> None:
    root = repo({"pkg/io.py": HANDLER_RETURN, "pkg/info.py": TWO_SHAPES})
    _stage(root, {"pkg/io.py": HANDLER_MOVED, "pkg/info.py": TWO_SHAPES_BUILT})
    policy = _policy(
        handlers=HandlersPolicy(enabled=False), returns=ReturnsPolicy(enabled=False)
    )
    assert (
        find_cases(root, policy, head=False),
        _keys(find_cases(root, default_policy(), head=False)),
    ) == ([], [("returns", "pkg/info.py::info"), ("handlers", "pkg/io.py::load")])


def test_test_paths_and_files_outside_include_make_no_case(repo: Repo) -> None:
    root = repo({"tests/test_io.py": HANDLER_RETURN, "scripts/io.py": HANDLER_RETURN})
    _stage(root, {"tests/test_io.py": HANDLER_MOVED, "scripts/io.py": HANDLER_MOVED})
    narrowed = _policy(handlers=HandlersPolicy(include=("pkg/**/*.py",)))
    assert (
        find_cases(root, narrowed, head=False),
        _keys(find_cases(root, default_policy(), head=False)),
    ) == ([], [("handlers", "scripts/io.py::load")])


def test_head_compares_head_with_its_first_parent(repo: Repo) -> None:
    root = repo({"pkg/io.py": HANDLER_RETURN})
    root_commit = find_cases(root, default_policy(), head=True)
    _stage(root, {"pkg/io.py": HANDLER_MOVED})
    staged = find_cases(root, default_policy(), head=True)
    _commit(root)
    assert (
        root_commit,
        staged,
        _keys(find_cases(root, default_policy(), head=True)),
        find_cases(root, default_policy(), head=False),
    ) == ([], [], [("handlers", "pkg/io.py::load")], [])


def test_the_staged_tree_is_compared_not_the_working_tree(repo: Repo) -> None:
    root = repo({"pkg/io.py": HANDLER_RETURN})
    (root / "pkg/io.py").write_text(HANDLER_MOVED, encoding="utf-8")
    unstaged = find_cases(root, default_policy(), head=False)
    _stage(root, {})
    assert (unstaged, _keys(find_cases(root, default_policy(), head=False))) == (
        [],
        [("handlers", "pkg/io.py::load")],
    )
