"""`filepawl hook`: the edit-time notice (docs/design.md §7.1)."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.cli import main
from filepawl.state import STATE_FILE

Repo = Callable[[dict[str, str | int]], Path]

# Default policy: cap 500, cap_tests 800, watch 400.
WATCH = 400
CAP = 500
CAP_TESTS = 800

DELEGATE = "Plan the split now; it is mechanical and can be delegated."


def lines(n: int, start: int = 1) -> str:
    return "".join(f"line {k}\n" for k in range(start, start + n))


def run_hook(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str | None:
    """Run `filepawl hook` on a payload; return the notice, or None when silent.

    Fails when the hook denies the edit instead.
    """
    specific = hook_output(payload, monkeypatch, capsys)
    if specific is None:
        return None
    assert "permissionDecision" not in specific
    return strip_prefix(specific["additionalContext"])


def run_hook_denied(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    """Run `filepawl hook` on a payload it must deny; return the reason."""
    specific = hook_output(payload, monkeypatch, capsys)
    assert specific is not None
    assert specific["permissionDecision"] == "deny"
    assert "additionalContext" not in specific
    return strip_prefix(specific["permissionDecisionReason"])


def hook_output(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object] | None:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    assert main(["hook"]) == 0
    out = capsys.readouterr().out
    if out == "":
        return None
    specific = json.loads(out)["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["hookEventName"] == "PreToolUse"
    return specific


def strip_prefix(text: object) -> str:
    assert isinstance(text, str)
    assert text.startswith("filepawl: ")
    return text.removeprefix("filepawl: ")


def write(root: Path, path: str, content: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(root),
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / path), "content": content},
    }


def edit(
    root: Path, path: str, old: str, new: str, replace_all: bool = False
) -> dict[str, object]:
    tool_input: dict[str, object] = {
        "file_path": str(root / path),
        "old_string": old,
        "new_string": new,
    }
    if replace_all:
        tool_input["replace_all"] = True
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(root),
        "tool_name": "Edit",
        "tool_input": tool_input,
    }


def with_allowance(root: Path, path: str, n: int) -> None:
    (root / STATE_FILE).write_text(
        f'version = 1\n\n[allowance]\n"{path}" = {{ lines = {n} }}\n',
        encoding="utf-8",
    )


# --- notices -------------------------------------------------------------


def test_edit_growing_a_ratcheted_file_past_its_allowance(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 10})
    with_allowance(root, "a.py", WATCH + 10)
    notice = run_hook(edit(root, "a.py", "line 1\n", lines(4)), monkeypatch, capsys)
    assert notice == (
        f"a.py: in the length ratchet at {WATCH + 10} lines; this edit takes it "
        f"{WATCH + 10} → {WATCH + 13}. 3 lines over the allowance; split them out "
        f"before committing. {DELEGATE}"
    )


def test_edit_inside_the_allowance_says_the_file_may_only_shrink(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 10})
    with_allowance(root, "a.py", WATCH + 10)
    notice = run_hook(edit(root, "a.py", "line 1\n", ""), monkeypatch, capsys)
    assert notice == (
        f"a.py: in the length ratchet at {WATCH + 10} lines; this edit takes it "
        f"{WATCH + 10} → {WATCH + 9}. It may shrink, never grow past {WATCH + 10}. "
        f"{DELEGATE}"
    )


def test_edit_crossing_the_watch_line_names_the_ratchet(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH})
    notice = run_hook(edit(root, "a.py", "line 1\n", lines(2)), monkeypatch, capsys)
    assert notice == (
        f"a.py: goes {WATCH} → {WATCH + 1} lines, over watch line {WATCH}; it "
        "enters the length ratchet on the next `filepawl accept` and may only "
        f"shrink after that. {DELEGATE}"
    )


def test_edit_growing_a_file_over_its_cap_is_denied(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP})
    with_allowance(root, "a.py", CAP)
    reason = run_hook_denied(
        edit(root, "a.py", "line 1\n", lines(3)), monkeypatch, capsys
    )
    assert reason == (
        f"a.py: this edit takes it {CAP} → {CAP + 2} lines, over cap {CAP}; "
        "blocked. Split the file first; the split is mechanical and can be "
        "delegated."
    )


def test_write_creating_a_file_over_its_cap_is_denied(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    reason = run_hook_denied(write(root, "new.py", lines(CAP + 1)), monkeypatch, capsys)
    assert reason.startswith(f"new.py: this edit takes it 0 → {CAP + 1} lines")


def test_over_cap_file_that_shrinks_gets_the_cap_sentence(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 10})
    with_allowance(root, "a.py", CAP + 10)
    notice = run_hook(edit(root, "a.py", "line 1\n", ""), monkeypatch, capsys)
    assert notice == (
        f"a.py: in the length ratchet at {CAP + 10} lines; this edit takes it "
        f"{CAP + 10} → {CAP + 9}. It may shrink, never grow past {CAP + 10}. "
        f"Over cap {CAP}; split it before committing. {DELEGATE}"
    )


def test_over_cap_file_that_keeps_its_length_is_not_denied(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 10})
    with_allowance(root, "a.py", CAP + 10)
    notice = run_hook(edit(root, "a.py", "line 1\n", "one\n"), monkeypatch, capsys)
    assert notice is not None
    assert f"Over cap {CAP}; split it before committing." in notice


def test_exempt_path_gets_no_cap_sentence(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "a.py": CAP,
            "pyproject.toml": '[tool.filepawl.exempt]\n"a.py" = "fixture"\n',
        }
    )
    with_allowance(root, "a.py", CAP)
    notice = run_hook(edit(root, "a.py", "line 1\n", lines(3)), monkeypatch, capsys)
    assert notice is not None
    assert "Over cap" not in notice


def test_write_creating_an_untracked_file_is_projected(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    notice = run_hook(write(root, "new.py", lines(WATCH + 5)), monkeypatch, capsys)
    assert notice is not None
    assert notice.startswith(f"new.py: goes 0 → {WATCH + 5} lines, over watch line")


def test_test_file_growing_over_its_cap_is_denied(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"tests/test_a.py": CAP_TESTS})
    reason = run_hook_denied(
        edit(root, "tests/test_a.py", "line 1\n", lines(2)), monkeypatch, capsys
    )
    assert reason.startswith(
        f"tests/test_a.py: this edit takes it {CAP_TESTS} → {CAP_TESTS + 1} "
        f"lines, over cap {CAP_TESTS}; blocked."
    )


def test_test_file_over_its_cap_that_shrinks(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"tests/test_a.py": CAP_TESTS + 5})
    notice = run_hook(
        edit(root, "tests/test_a.py", "line 1\n", ""), monkeypatch, capsys
    )
    assert notice == (
        f"tests/test_a.py: test file goes {CAP_TESTS + 5} → {CAP_TESTS + 4} "
        f"lines, over cap {CAP_TESTS}; split it before committing."
    )


def test_exempt_test_file_growing_over_its_cap_is_not_denied(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "tests/test_a.py": CAP_TESTS,
            "pyproject.toml": '[tool.filepawl.exempt]\n"tests/test_a.py" = "oracle"\n',
        }
    )
    assert (
        run_hook(
            edit(root, "tests/test_a.py", "line 1\n", lines(2)), monkeypatch, capsys
        )
        is None
    )


def test_test_file_over_watch_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"tests/test_a.py": WATCH + 10})
    assert (
        run_hook(
            edit(root, "tests/test_a.py", "line 1\n", lines(2)), monkeypatch, capsys
        )
        is None
    )


# --- projection ----------------------------------------------------------


def test_replace_all_replaces_every_occurrence(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": "x\n" * 10 + lines(WATCH - 10)})
    notice = run_hook(
        edit(root, "a.py", "x\n", "x\ny\n", replace_all=True), monkeypatch, capsys
    )
    assert notice is not None
    assert f"goes {WATCH} → {WATCH + 10} lines" in notice


def test_edit_without_replace_all_replaces_once(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": "x\n" * WATCH})
    notice = run_hook(edit(root, "a.py", "x\n", "x\ny\n"), monkeypatch, capsys)
    assert notice is not None
    assert f"goes {WATCH} → {WATCH + 1} lines" in notice


def test_multiedit_applies_edits_in_order(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH})
    payload = {
        "cwd": str(root),
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": str(root / "a.py"),
            "edits": [
                {"old_string": "line 1\n", "new_string": "first\n"},
                {"old_string": "first\n", "new_string": "first\nsecond\nthird\n"},
            ],
        },
    }
    notice = run_hook(payload, monkeypatch, capsys)
    assert notice is not None
    assert f"goes {WATCH} → {WATCH + 2} lines" in notice


# --- silence -------------------------------------------------------------


def test_under_the_watch_line_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 10})
    assert (
        run_hook(edit(root, "a.py", "line 1\n", lines(5)), monkeypatch, capsys) is None
    )


def test_edit_shrinking_under_the_watch_line_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    with_allowance(root, "a.py", WATCH + 1)
    assert run_hook(edit(root, "a.py", "line 1\n", ""), monkeypatch, capsys) is None


def test_other_tools_are_ignored(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 50})
    payload = {
        "cwd": str(root),
        "tool_name": "Read",
        "tool_input": {"file_path": str(root / "a.py")},
    }
    assert run_hook(payload, monkeypatch, capsys) is None


def test_path_outside_every_include_is_ignored(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    assert (
        run_hook(write(root, "notes.md", lines(CAP + 5)), monkeypatch, capsys) is None
    )


def test_disabled_length_gate_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {"a.py": 1, "pyproject.toml": "[tool.filepawl.length]\nenabled = false\n"}
    )
    assert run_hook(write(root, "b.py", lines(CAP + 5)), monkeypatch, capsys) is None


def test_path_outside_the_repository_is_silent(
    repo: Repo,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = repo({"a.py": 1})
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    payload = write(root, "a.py", lines(CAP + 5))
    payload["tool_input"] = {
        "file_path": str(elsewhere / "b.py"),
        "content": lines(CAP + 5),
    }
    assert run_hook(payload, monkeypatch, capsys) is None


def test_old_string_that_does_not_occur_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 10})
    with_allowance(root, "a.py", WATCH + 10)
    assert (
        run_hook(edit(root, "a.py", "absent\n", lines(50)), monkeypatch, capsys) is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        {"tool_name": "Write"},
        {"cwd": 3, "tool_name": "Write", "tool_input": {}},
        {"cwd": "/", "tool_name": "Write", "tool_input": {"file_path": 3}},
    ],
)
def test_malformed_payload_is_silent(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_hook(payload, monkeypatch, capsys) is None


def test_directory_outside_any_repository_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "a.py"), "content": lines(CAP)},
    }
    assert run_hook(payload, monkeypatch, capsys) is None


def test_broken_policy_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1, "pyproject.toml": "[tool.filepawl]\nbogus = 1\n"})
    assert run_hook(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys) is None


def test_broken_state_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    (root / STATE_FILE).write_text("version = 99\n", encoding="utf-8")
    assert run_hook(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys) is None
