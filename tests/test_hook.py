"""`filepawl hook`: the edit-time notice (docs/design.md §7.1)."""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.hook import run_hook as _run_hook
from filepawl.state import STATE_FILE

FILEPAWL = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "filepawl"

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
    out = io.StringIO()
    assert _run_hook(io.StringIO(text), out) == 0
    output = out.getvalue()
    if output == "":
        return None
    specific = json.loads(output)["hookSpecificOutput"]
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
            "tests/test_b.py": CAP_TESTS,
            "pyproject.toml": '[tool.filepawl.exempt]\n"tests/test_a.py" = "oracle"\n',
        }
    )
    exempt = run_hook(
        edit(root, "tests/test_a.py", "line 1\n", lines(2)), monkeypatch, capsys
    )
    reason = run_hook_denied(
        edit(root, "tests/test_b.py", "line 1\n", lines(2)), monkeypatch, capsys
    )
    assert exempt is None
    assert reason.startswith(
        f"tests/test_b.py: this edit takes it {CAP_TESTS} → {CAP_TESTS + 1} lines"
    )


def test_test_file_over_watch_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"tests/test_a.py": WATCH + 10, "a.py": WATCH + 10})
    test_file = run_hook(
        edit(root, "tests/test_a.py", "line 1\n", lines(2)), monkeypatch, capsys
    )
    source = run_hook(edit(root, "a.py", "line 1\n", lines(2)), monkeypatch, capsys)
    assert test_file is None
    assert source is not None
    assert source.startswith(f"a.py: goes {WATCH + 10} → {WATCH + 11} lines")


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
    under = run_hook(edit(root, "a.py", "line 1\n", lines(5)), monkeypatch, capsys)
    over = run_hook(edit(root, "a.py", "line 1\n", lines(WATCH)), monkeypatch, capsys)
    assert under is None
    assert over is not None
    assert over.startswith(f"a.py: goes 10 → {WATCH + 9} lines, over watch line")


def test_edit_shrinking_under_the_watch_line_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 1})
    with_allowance(root, "a.py", WATCH + 1)
    shrunk = run_hook(edit(root, "a.py", "line 1\n", ""), monkeypatch, capsys)
    kept = run_hook(edit(root, "a.py", "line 1\n", "one\n"), monkeypatch, capsys)
    assert shrunk is None
    assert kept is not None
    assert kept.startswith(f"a.py: in the length ratchet at {WATCH + 1} lines")


def test_other_tools_are_ignored(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": CAP + 50})
    payload = {
        "cwd": str(root),
        "tool_name": "Read",
        "tool_input": {"file_path": str(root / "a.py")},
    }
    read = run_hook(payload, monkeypatch, capsys)
    edited = run_hook(edit(root, "a.py", "line 1\n", "one\n"), monkeypatch, capsys)
    assert read is None
    assert edited is not None
    assert edited.startswith(f"a.py: goes {CAP + 50} → {CAP + 50} lines")


def test_path_outside_every_include_is_ignored(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    notes = run_hook(write(root, "notes.md", lines(CAP + 5)), monkeypatch, capsys)
    reason = run_hook_denied(
        write(root, "notes.py", lines(CAP + 5)), monkeypatch, capsys
    )
    assert notes is None
    assert reason.startswith(f"notes.py: this edit takes it 0 → {CAP + 5} lines")


def test_disabled_length_gate_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {"a.py": 1, "pyproject.toml": "[tool.filepawl.length]\nenabled = false\n"}
    )
    disabled = run_hook(write(root, "b.py", lines(CAP + 5)), monkeypatch, capsys)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    reason = run_hook_denied(write(root, "b.py", lines(CAP + 5)), monkeypatch, capsys)
    assert disabled is None
    assert reason.startswith(f"b.py: this edit takes it 0 → {CAP + 5} lines")


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
    outside = run_hook(payload, monkeypatch, capsys)
    reason = run_hook_denied(write(root, "b.py", lines(CAP + 5)), monkeypatch, capsys)
    assert outside is None
    assert reason.startswith(f"b.py: this edit takes it 0 → {CAP + 5} lines")


def test_old_string_that_does_not_occur_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": WATCH + 10})
    with_allowance(root, "a.py", WATCH + 10)
    absent = run_hook(edit(root, "a.py", "absent\n", lines(50)), monkeypatch, capsys)
    present = run_hook(edit(root, "a.py", "line 1\n", lines(50)), monkeypatch, capsys)
    assert absent is None
    assert present is not None
    assert present.startswith(
        f"a.py: in the length ratchet at {WATCH + 10} lines; this edit takes it "
        f"{WATCH + 10} → {WATCH + 59}."
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
    repo: Repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = repo({"a.py": 1})
    malformed = run_hook(payload, monkeypatch, capsys)
    reason = run_hook_denied(write(root, "b.py", lines(CAP + 5)), monkeypatch, capsys)
    assert malformed is None
    assert reason.startswith(f"b.py: this edit takes it 0 → {CAP + 5} lines")


def test_directory_outside_any_repository_is_silent(
    tmp_path: Path,
    repo: Repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "a.py"), "content": lines(CAP)},
    }
    outside = run_hook(payload, monkeypatch, capsys)
    repo({"b.py": 1})
    inside = run_hook(payload, monkeypatch, capsys)
    assert outside is None
    assert inside is not None
    assert inside.startswith(f"a.py: goes 0 → {CAP} lines, over watch line {WATCH}")


def test_broken_policy_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1, "pyproject.toml": "[tool.filepawl]\nbogus = 1\n"})
    broken = run_hook(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    reason = run_hook_denied(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys)
    assert broken is None
    assert reason.startswith(f"a.py: this edit takes it 1 → {CAP + 5} lines")


def test_broken_state_is_silent(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"a.py": 1})
    (root / STATE_FILE).write_text("version = 99\n", encoding="utf-8")
    broken = run_hook(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys)
    (root / STATE_FILE).unlink()
    reason = run_hook_denied(write(root, "a.py", lines(CAP + 5)), monkeypatch, capsys)
    assert broken is None
    assert reason.startswith(f"a.py: this edit takes it 1 → {CAP + 5} lines")


# --- subprocess ------------------------------------------------------------


def test_installed_hook_runs_as_a_subprocess(repo: Repo) -> None:
    root = repo({"a.py": WATCH})
    payload = edit(root, "a.py", "line 1\n", lines(2))
    result = subprocess.run(
        [str(FILEPAWL), "hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    specific = json.loads(result.stdout)["hookSpecificOutput"]
    notice = strip_prefix(specific["additionalContext"])
    assert notice == (
        f"a.py: goes {WATCH} → {WATCH + 1} lines, over watch line {WATCH}; it "
        "enters the length ratchet on the next `filepawl accept` and may only "
        f"shrink after that. {DELEGATE}"
    )
