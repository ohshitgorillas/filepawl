"""Judge transport: the `claude` call and the answer reader (docs/design.md §7.2)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from filepawl.config import JudgePolicy
from filepawl.errors import JudgeError
from filepawl.judge.cases import Case
from filepawl.judge.prompt import PROMPT
from filepawl.judge.transport import Verdict, ask_judge

if TYPE_CHECKING:
    from conftest import FakeClaude

POLICY = JudgePolicy(enabled=True, batch=2)
DODGE = ("dodge", "the default stands in for the failed read")


def _case(name: str, gate: str = "handlers") -> Case:
    return Case(
        gate=gate,
        key=f"pkg/a.py::{name}",
        old=f"def {name}():\n    old()",
        new=f"def {name}():\n    new()",
        helpers=(),
    )


def _verdicts(verdicts: list[Verdict]) -> list[tuple[str, str, str]]:
    return [(v.case.key, v.verdict, v.reason) for v in verdicts]


def test_a_call_runs_claude_in_print_mode_with_the_prompt_and_cases(
    fake_claude: FakeClaude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    fake_claude.answer({"pkg/a.py::f": DODGE})
    case = Case(
        gate="returns",
        key="pkg/a.py::f",
        old="def f():\n    old()",
        new="def f():\n    new()",
        helpers=(("_shape", "def _shape():\n    return {}"),),
    )
    verdicts = ask_judge(tmp_path, [case], JudgePolicy(model="claude-opus-5"))
    [call] = fake_claude.calls()
    assert (
        _verdicts(verdicts),
        call["argv"],
        call["cwd"],
        call["inner"],
        call["claudecode"],
        call["stdin"],
    ) == (
        [("pkg/a.py::f", *DODGE)],
        [
            "-p",
            "--model",
            "claude-opus-5",
            "--tools",
            "",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--output-format",
            "json",
        ],
        str(tmp_path.resolve()),
        "1",
        None,
        (
            PROMPT
            + "\nCASES:\n\n"
            + "### CASE 1\nGATE: returns\nFUNCTION: pkg/a.py::f\n"
            + "BEFORE:\ndef f():\n    old()\n"
            + "AFTER:\ndef f():\n    new()\n"
            + "HELPERS:\n# helper added in the same file: _shape\n"
            + "def _shape():\n    return {}\n\n"
        ),
    )


def test_cases_go_in_calls_of_batch_cases_each(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.answer({"pkg/a.py::c": DODGE})
    cases = [_case(name) for name in "abcde"]
    verdicts = ask_judge(tmp_path, cases, POLICY)
    sizes = [str(call["stdin"]).count("### CASE") for call in fake_claude.calls()]
    assert (sizes, [v.verdict for v in verdicts]) == (
        [2, 2, 1],
        ["clean", "clean", "dodge", "clean", "clean"],
    )


@pytest.mark.parametrize(
    "wrap",
    [
        "```json\nANSWERS\n```",
        "ANSWERS\nThe second case [1] needed a closer look.",
        "Verdicts follow.\nANSWERS",
    ],
)
def test_a_fenced_answer_and_text_around_the_array_are_read(
    fake_claude: FakeClaude, tmp_path: Path, wrap: str
) -> None:
    fake_claude.answer({"pkg/a.py::g": DODGE}, {"wrap": wrap})
    verdicts = ask_judge(tmp_path, [_case("f"), _case("g")], POLICY)
    assert (_verdicts(verdicts), len(fake_claude.calls())) == (
        [
            ("pkg/a.py::f", "clean", "the failure propagates"),
            ("pkg/a.py::g", *DODGE),
        ],
        1,
    )


@pytest.mark.parametrize(
    "unreadable",
    [
        {"stdout": "not an envelope"},
        {"stdout": '{"is_error": true, "result": "[]"}'},
        {"wrap": "I cannot judge these."},
        {"exit": 1},
    ],
)
def test_an_unreadable_answer_is_asked_once_more(
    fake_claude: FakeClaude, tmp_path: Path, unreadable: dict[str, object]
) -> None:
    fake_claude.answer({"pkg/a.py::f": DODGE}, unreadable, {})
    verdicts = ask_judge(tmp_path, [_case("f")], POLICY)
    assert (_verdicts(verdicts), len(fake_claude.calls())) == (
        [("pkg/a.py::f", *DODGE)],
        2,
    )


def test_a_call_failing_twice_is_a_judge_error(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.answer({}, {"exit": 3})
    with pytest.raises(JudgeError, match="exited 3"):
        ask_judge(tmp_path, [_case("f")], POLICY)
    assert len(fake_claude.calls()) == 2


def test_unanswered_cases_are_asked_once_more_together(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.answer(
        {"pkg/a.py::b": DODGE},
        {"omit": ["pkg/a.py::b"]},
        {"omit": ["pkg/a.py::c"]},
        {},
    )
    verdicts = ask_judge(tmp_path, [_case(name) for name in "abcd"], POLICY)
    retry = str(fake_claude.calls()[-1]["stdin"])
    assert (
        len(fake_claude.calls()),
        retry.count("### CASE"),
        "FUNCTION: pkg/a.py::b" in retry,
        [v.verdict for v in verdicts],
    ) == (3, 2, True, ["clean", "dodge", "clean", "clean"])


def test_a_case_still_unanswered_is_a_dodge(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.answer({}, {"omit": ["pkg/a.py::b"]})
    verdicts = ask_judge(tmp_path, [_case("a"), _case("b")], POLICY)
    assert (_verdicts(verdicts), len(fake_claude.calls())) == (
        [
            ("pkg/a.py::a", "clean", "the failure propagates"),
            ("pkg/a.py::b", "dodge", "no verdict"),
        ],
        2,
    )


def test_an_answer_naming_no_verdict_leaves_the_case_unanswered(
    fake_claude: FakeClaude, tmp_path: Path
) -> None:
    fake_claude.answer({"pkg/a.py::a": ("maybe", "hard to say")})
    verdicts = ask_judge(tmp_path, [_case("a")], POLICY)
    assert (_verdicts(verdicts), len(fake_claude.calls())) == (
        [("pkg/a.py::a", "dodge", "no verdict")],
        2,
    )


def test_a_missing_claude_is_a_judge_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(JudgeError, match="claude"):
        ask_judge(tmp_path, [_case("f")], POLICY)
    assert shutil.which("claude") is None
