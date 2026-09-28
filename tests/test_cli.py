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
    status = main(["check"])
    captured = capsys.readouterr()
    (root / "pkg/a.py").write_text("line\n" * (WATCH + 1), encoding="utf-8")
    grown = main(["check"])
    grown_out = capsys.readouterr().out
    assert (
        status,
        captured.out,
        captured.err,
        grown,
        grown_out.endswith("filepawl accept pkg/a.py\n"),
    ) == (0, "", "", 1, True)


def test_check_prints_findings_sorted_then_the_accept_command(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"b.py": WATCH + 1, "a.py": WATCH + 1})
    monkeypatch.chdir(root)
    status = main(["check"])
    lines = capsys.readouterr().out.splitlines()
    assert (status, lines) == (
        1,
        [
            f"a.py: over watch line {WATCH} ({WATCH + 1} lines); "
            "run `filepawl accept a.py`",
            f"b.py: over watch line {WATCH} ({WATCH + 1} lines); "
            "run `filepawl accept b.py`",
            "filepawl accept a.py b.py",
        ],
    )


def test_check_sorts_two_findings_for_one_path_by_message(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 1})
    monkeypatch.chdir(root)
    status = main(["check"])
    lines = capsys.readouterr().out.splitlines()
    assert (status, lines) == (
        1,
        [
            f"a.py: over cap {CAP} ({CAP + 1} lines); split it",
            f"a.py: over watch line {WATCH} ({CAP + 1} lines); "
            "run `filepawl accept a.py`",
            "filepawl accept a.py",
        ],
    )


def test_check_prints_bare_accept_when_only_stale_entries_are_fixable(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, 'version = 1\n\n[allowance]\n"gone.py" = { lines = 450 }\n')
    monkeypatch.chdir(root)
    status = main(["check"])
    lines = capsys.readouterr().out.splitlines()
    assert (status, lines) == (
        1,
        [
            "gone.py: allowance names a path outside the tree; drop it",
            "filepawl accept",
        ],
    )


def test_check_path_argument_narrows_the_measured_set(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    status = main(["check", "a.py"])
    lines = capsys.readouterr().out.splitlines()
    assert (status, lines) == (
        1,
        [
            f"a.py: over watch line {WATCH} ({WATCH + 1} lines); "
            "run `filepawl accept a.py`",
            "filepawl accept a.py",
        ],
    )


def test_check_dot_path_means_the_whole_tree(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    status = main(["check", "."])
    last = capsys.readouterr().out.splitlines()[-1]
    assert (status, last) == (1, "filepawl accept a.py b.py")


def test_check_path_outside_the_repository_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit, match="^2$"):
        main(["check", "/etc"])
    err = capsys.readouterr().err
    assert (err.startswith("filepawl: "), "outside the repository" in err) == (
        True,
        True,
    )


def test_check_exits_two_on_an_unparseable_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, "version = \n")
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit, match="^2$"):
        main(["check"])
    err = capsys.readouterr().err
    assert (err.startswith("filepawl: "), "unparseable TOML" in err) == (True, True)


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
    with pytest.raises(SystemExit, match="^2$"):
        main(["check"])
    err = capsys.readouterr().err
    assert (err.startswith("filepawl: "), "unknown mover" in err) == (True, True)


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
    status = main(["check"])
    out = capsys.readouterr().out
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace('"command"', '"nosuch"'), encoding="utf-8")
    with pytest.raises(SystemExit, match="^2$"):
        main(["check"])
    err = capsys.readouterr().err
    assert (status, out, "unknown mover" in err) == (0, "", True)


# --- accept ------------------------------------------------------------


def test_accept_adds_a_missing_entry_and_exits_zero(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    status = main(["accept"])
    out = capsys.readouterr().out
    assert (status, out, allowance_of(root)) == (0, "", {"a.py": {"lines": WATCH + 1}})


def test_accept_does_not_rewrite_an_unchanged_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1})
    text = f'version = 1\n[allowance]\n"a.py" = {{lines = {WATCH + 1}}}\n'
    write_state_text(root, text)
    monkeypatch.chdir(root)
    status = main(["accept"])
    after = (root / STATE_FILE).read_text(encoding="utf-8")
    assert (status, after) == (0, text)


def test_accept_narrowed_to_one_path_leaves_the_other_pending(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    accepted = main(["accept", "a.py"])
    accept_out = capsys.readouterr().out
    allowance = allowance_of(root)
    checked = main(["check"])
    check_lines = capsys.readouterr().out.splitlines()
    assert (accepted, accept_out, allowance, checked, check_lines) == (
        0,
        "",
        {"a.py": {"lines": WATCH + 1}},
        1,
        [
            f"b.py: over watch line {WATCH} ({WATCH + 1} lines); "
            "run `filepawl accept b.py`",
            "filepawl accept b.py",
        ],
    )


def test_accept_of_a_grown_file_reports_it_and_exits_one(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 450})
    write_state_text(root, 'version = 1\n\n[allowance]\n"a.py" = { lines = 420 }\n')
    monkeypatch.chdir(root)
    status = main(["accept"])
    lines = capsys.readouterr().out.splitlines()
    assert (status, lines, allowance_of(root)) == (
        1,
        ["a.py: grew past allowance (450 > 420); split it"],
        {"a.py": {"lines": 420}},
    )


def test_accept_drops_a_stale_entry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    write_state_text(root, 'version = 1\n\n[allowance]\n"gone.py" = { lines = 450 }\n')
    monkeypatch.chdir(root)
    before = allowance_of(root)
    status = main(["accept"])
    out = capsys.readouterr().out
    assert (before, status, out, allowance_of(root)) == (
        {"gone.py": {"lines": 450}},
        0,
        "",
        {},
    )


def test_accept_reason_sets_the_reason_on_that_entry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    status = main(["accept", "a.py", "--reason", "line record plus its readers"])
    assert (status, allowance_of(root)) == (
        0,
        {"a.py": {"lines": WATCH + 1, "reason": "line record plus its readers"}},
    )


def test_accept_reason_without_a_path_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit, match="^2$"):
        main(["accept", "--reason", "why"])
    err = capsys.readouterr().err
    assert (
        err.startswith("filepawl: "),
        "--reason" in err,
        (root / STATE_FILE).exists(),
    ) == (True, True, False)


def test_accept_reason_with_two_paths_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit, match="^2$"):
        main(["accept", "a.py", "b.py", "--reason", "why"])
    err = capsys.readouterr().err
    assert ("--reason" in err, (root / STATE_FILE).exists()) == (True, False)


def test_accept_reason_for_a_path_with_no_entry_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit, match="^2$"):
        main(["accept", "a.py", "--reason", "why"])
    err = capsys.readouterr().err
    assert (err.startswith("filepawl: "), "no allowance entry" in err) == (True, True)


# --- init --------------------------------------------------------------


def test_init_writes_state_and_the_policy_stub(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1, "pyproject.toml": PYPROJECT})
    monkeypatch.chdir(root)
    status = main(["init"])
    allowance = allowance_of(root)
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        status,
        allowance,
        text.startswith(PYPROJECT),
        "# [tool.filepawl]" in text,
        tomllib.loads(text),
    ) == (0, {"a.py": {"lines": WATCH + 1}}, True, True, tomllib.loads(PYPROJECT))


def test_init_appends_the_policy_stub_once(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": WATCH + 1, "pyproject.toml": PYPROJECT})
    monkeypatch.chdir(root)
    first = main(["init"])
    (root / STATE_FILE).unlink()
    second = main(["init"])
    again = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (first, second, again.count("# [tool.filepawl]")) == (0, 0, 1)


def test_init_refuses_an_existing_state_file(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10, "pyproject.toml": PYPROJECT})
    monkeypatch.chdir(root)
    status = main(["init"])
    with pytest.raises(SystemExit, match="^2$"):
        main(["init"])
    err = capsys.readouterr().err
    assert (status, err.startswith("filepawl: "), STATE_FILE in err) == (0, True, True)


def test_init_creates_pyproject_when_it_is_missing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    status = main(["init"])
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (status, "# [tool.filepawl]" in text, tomllib.loads(text)) == (0, True, {})


def test_init_leaves_pyproject_alone_when_tool_filepawl_is_present(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = PYPROJECT + '\n[tool.filepawl]\ntests = ["tests/**"]\n'
    root = repo({"a.py": 10, "pyproject.toml": configured})
    monkeypatch.chdir(root)
    status = main(["init"])
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (status, text) == (0, configured)


# --- no subcommand ------------------------------------------------------
# `mv` itself is covered by tests/test_mv.py.


def test_no_subcommand_prints_usage_and_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    monkeypatch.chdir(root)
    status = main([])
    captured = capsys.readouterr()
    assert (status, "usage: filepawl" in captured.err, captured.out) == (2, True, "")
