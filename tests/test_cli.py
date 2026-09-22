"""CLI: `check`, `accept` and `init` (docs/design.md §6.4, §7)."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.cli import main
from filepawl.state import STATE_FILE

Repo = Callable[[dict[str, str | int]], Path]

# Default policy: cap 500, cap_tests 800, watch 400, dircount cap 15.
WATCH = 400
CAP = 500

PYPROJECT = '[project]\nname = "sample"\nversion = "0.0.0"\n'


def state_of(root: Path) -> dict[str, object]:
    return tomllib.loads((root / STATE_FILE).read_text(encoding="utf-8"))


def allowance_of(root: Path) -> dict[str, object]:
    table = state_of(root).get("allowance", {})
    assert isinstance(table, dict)
    return table


def write_state_text(root: Path, text: str) -> None:
    (root / STATE_FILE).write_text(text, encoding="utf-8")


# --- check -------------------------------------------------------------


def test_check_on_a_clean_tree_is_silent_and_exits_zero(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"pkg/a.py": 10})
    monkeypatch.chdir(root)
    assert main(["check"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_check_prints_findings_sorted_then_the_accept_command(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"b.py": WATCH + 1, "a.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"a.py: over watch line {WATCH} ({WATCH + 1} lines); "
        "run `filepawl accept a.py`",
        f"b.py: over watch line {WATCH} ({WATCH + 1} lines); "
        "run `filepawl accept b.py`",
        "filepawl accept a.py b.py",
    ]


def test_check_sorts_two_findings_for_one_path_by_message(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 1})
    monkeypatch.chdir(root)
    assert main(["check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"a.py: over cap {CAP} ({CAP + 1} lines); split it",
        f"a.py: over watch line {WATCH} ({CAP + 1} lines); "
        "run `filepawl accept a.py`",
        "filepawl accept a.py",
    ]


def test_check_prints_bare_accept_when_only_stale_entries_are_fixable(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, 'version = 1\n\n[allowance]\n"gone.py" = { lines = 450 }\n')
    monkeypatch.chdir(root)
    assert main(["check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "gone.py: allowance names a path outside the tree; drop it",
        "filepawl accept",
    ]


def test_check_path_argument_narrows_the_measured_set(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["check", "a.py"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"a.py: over watch line {WATCH} ({WATCH + 1} lines); "
        "run `filepawl accept a.py`",
        "filepawl accept a.py",
    ]


def test_check_dot_path_means_the_whole_tree(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["check", "."]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "filepawl accept a.py b.py"


def test_check_path_outside_the_repository_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    assert main(["check", "/etc"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert "outside the repository" in err


def test_check_exits_two_on_an_unparseable_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, "version = \n")
    monkeypatch.chdir(root)
    assert main(["check"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert "unparseable TOML" in err


def test_check_exits_two_on_an_unknown_mover(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "a.py": 10,
            "pyproject.toml": PYPROJECT
            + '\n[tool.filepawl]\nlanguages = ["python"]\n'
            + '\n[tool.filepawl.python]\ninclude = ["**/*.py"]\nmover = "nope"\n',
        }
    )
    monkeypatch.chdir(root)
    assert main(["check"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert "unknown mover" in err


def test_check_accepts_a_known_mover_name(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "a.py": 10,
            "pyproject.toml": PYPROJECT
            + '\n[tool.filepawl]\nlanguages = ["python"]\n'
            + '\n[tool.filepawl.python]\ninclude = ["**/*.py"]\nmover = "command"\n',
        }
    )
    monkeypatch.chdir(root)
    assert main(["check"]) == 0
    assert capsys.readouterr().out == ""


# --- accept ------------------------------------------------------------


def test_accept_adds_a_missing_entry_and_exits_zero(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["accept"]) == 0
    assert capsys.readouterr().out == ""
    assert allowance_of(root) == {"a.py": {"lines": WATCH + 1}}


def test_accept_does_not_rewrite_an_unchanged_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1})
    text = f'version = 1\n[allowance]\n"a.py" = {{lines = {WATCH + 1}}}\n'
    write_state_text(root, text)
    monkeypatch.chdir(root)
    assert main(["accept"]) == 0
    assert (root / STATE_FILE).read_text(encoding="utf-8") == text


def test_accept_narrowed_to_one_path_leaves_the_other_pending(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["accept", "a.py"]) == 0
    assert capsys.readouterr().out == ""
    assert allowance_of(root) == {"a.py": {"lines": WATCH + 1}}
    assert main(["check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"b.py: over watch line {WATCH} ({WATCH + 1} lines); "
        "run `filepawl accept b.py`",
        "filepawl accept b.py",
    ]


def test_accept_of_a_grown_file_reports_it_and_exits_one(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 450})
    write_state_text(root, 'version = 1\n\n[allowance]\n"a.py" = { lines = 420 }\n')
    monkeypatch.chdir(root)
    assert main(["accept"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "a.py: grew past allowance (450 > 420); split it"
    ]
    assert allowance_of(root) == {"a.py": {"lines": 420}}


def test_accept_drops_a_stale_entry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, 'version = 1\n\n[allowance]\n"gone.py" = { lines = 450 }\n')
    monkeypatch.chdir(root)
    assert main(["accept"]) == 0
    assert capsys.readouterr().out == ""
    assert allowance_of(root) == {}


def test_accept_reason_sets_the_reason_on_that_entry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["accept", "a.py", "--reason", "line record plus its readers"]) == 0
    assert allowance_of(root) == {
        "a.py": {"lines": WATCH + 1, "reason": "line record plus its readers"}
    }


def test_accept_reason_without_a_path_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["accept", "--reason", "why"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert "--reason" in err
    assert not (root / STATE_FILE).exists()


def test_accept_reason_with_two_paths_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    assert main(["accept", "a.py", "b.py", "--reason", "why"]) == 2
    assert "--reason" in capsys.readouterr().err
    assert not (root / STATE_FILE).exists()


def test_accept_reason_for_a_path_with_no_entry_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    assert main(["accept", "a.py", "--reason", "why"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert "no allowance entry" in err


# --- init --------------------------------------------------------------


def test_init_writes_state_and_appends_the_policy_stub_once(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1, "pyproject.toml": PYPROJECT})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert allowance_of(root) == {"a.py": {"lines": WATCH + 1}}

    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert text.startswith(PYPROJECT)
    assert "# [tool.filepawl]" in text
    assert tomllib.loads(text) == tomllib.loads(PYPROJECT)

    (root / STATE_FILE).unlink()
    assert main(["init"]) == 0
    again = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert again.count("# [tool.filepawl]") == 1


def test_init_refuses_an_existing_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10, "pyproject.toml": PYPROJECT})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["init"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("filepawl: ")
    assert STATE_FILE in err


def test_init_creates_pyproject_when_it_is_missing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "# [tool.filepawl]" in text
    assert tomllib.loads(text) == {}


def test_init_leaves_pyproject_alone_when_tool_filepawl_is_present(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = PYPROJECT + '\n[tool.filepawl]\ntests = ["tests/**"]\n'
    root = repo({"a.py": 10, "pyproject.toml": configured})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == configured


# --- no subcommand ------------------------------------------------------
# `mv` itself is covered by tests/test_mv.py.


def test_no_subcommand_prints_usage_and_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    assert main([]) == 2
    assert "usage: filepawl" in capsys.readouterr().out
