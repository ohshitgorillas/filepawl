"""Judge transport: the `claude` CLI call and the answer reader (design.md §7.2).

Cases go to `claude` in print mode, `batch` to a call, behind the fixed
prompt. A call that fails or answers with no readable array is made once
more, and a second failure is a `JudgeError`. Cases the answers leave
without a verdict are asked once more together; a case still without one
is a dodge with the reason `no verdict`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from filepawl.config import JudgePolicy
from filepawl.errors import JudgeError
from filepawl.judge.cases import Case
from filepawl.judge.prompt import PROMPT

_VERDICTS = ("dodge", "clean")
_NO_VERDICT = ("dodge", "no verdict")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

# (verdict, reason) per case, by the case's position in the run.
_Answers = dict[int, tuple[str, str]]


@dataclass(frozen=True)
class Verdict:
    """The judge's answer on one case: `dodge` or `clean`, with its reason."""

    case: Case
    verdict: str
    reason: str


class _CallFailed(Exception):
    """One call to `claude` gave no readable answer."""


def ask_judge(root: Path, cases: list[Case], policy: JudgePolicy) -> list[Verdict]:
    """Return one verdict per case, in the order of `cases`."""
    claude = shutil.which("claude")
    if claude is None:
        raise JudgeError("`claude` is not on PATH; the judge runs through it")
    command = [
        claude,
        "-p",
        "--model",
        policy.model,
        "--tools",
        "",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    call = _Call(root, command, policy.timeout, cases)
    answers: _Answers = {}
    for start in range(0, len(cases), policy.batch):
        answers |= call.ask(list(range(start, min(start + policy.batch, len(cases)))))
    unanswered = [index for index in range(len(cases)) if index not in answers]
    if unanswered:
        answers |= call.ask(unanswered)
    return [
        Verdict(case, *answers.get(index, _NO_VERDICT))
        for index, case in enumerate(cases)
    ]


@dataclass(frozen=True)
class _Call:
    """What every call of one run shares: where, how, and the run's cases."""

    root: Path
    command: list[str]
    timeout: int
    cases: list[Case]

    def ask(self, indices: list[int]) -> _Answers:
        """Ask about the cases at `indices`, numbered 1 up within this call."""
        body = PROMPT + "\nCASES:\n\n"
        body += "".join(
            _render(number, self.cases[index])
            for number, index in enumerate(indices, start=1)
        )
        answers: _Answers = {}
        for item in self._answer(body):
            if not isinstance(item, dict):
                continue
            number = str(item.get("id", ""))
            verdict = str(item.get("verdict", "")).strip().lower()
            if not number.isdigit() or not 1 <= int(number) <= len(indices):
                continue
            if verdict in _VERDICTS:
                index = indices[int(number) - 1]
                answers.setdefault(index, (verdict, str(item.get("reason", ""))))
        return answers

    def _answer(self, body: str) -> list[object]:
        """Return the answer array, making the call once more if the first fails."""
        failures: list[str] = []
        for _ in range(2):
            try:
                return self._attempt(body)
            except _CallFailed as exc:
                failures.append(str(exc))
        raise JudgeError("`claude` failed twice: " + "; then ".join(failures))

    def _attempt(self, body: str) -> list[object]:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["FILEPAWL_JUDGE_INNER"] = "1"
        try:
            done = subprocess.run(
                self.command,
                input=body,
                capture_output=True,
                text=True,
                cwd=self.root,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise _CallFailed(f"ran past {self.timeout} seconds") from exc
        except OSError as exc:
            raise _CallFailed(f"could not run: {exc}") from exc
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip()[:300]
            raise _CallFailed(f"exited {done.returncode}: {detail}")
        return _read(done.stdout)


def _render(number: int, case: Case) -> str:
    helpers = "".join(
        f"\n# helper added in the same file: {name}\n{source}\n"
        for name, source in case.helpers
    )
    return (
        f"### CASE {number}\nGATE: {case.gate}\nFUNCTION: {case.key}\n"
        f"BEFORE:\n{case.old}\n"
        f"AFTER:\n{case.new}\n" + (f"HELPERS:{helpers}" if helpers else "") + "\n"
    )


def _read(stdout: str) -> list[object]:
    """Return the first JSON array in the envelope's `result`."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise _CallFailed("printed no JSON envelope") from exc
    if not isinstance(envelope, dict):
        raise _CallFailed("printed no JSON envelope")
    result = envelope.get("result")
    if envelope.get("is_error") is True:
        raise _CallFailed(f"reported an error: {str(result)[:300]}")
    if not isinstance(result, str):
        raise _CallFailed("printed an envelope with no result")
    text = _FENCE.sub("", result.strip())
    decoder = json.JSONDecoder()
    for bracket in re.finditer(r"\[", text):
        try:
            value, _ = decoder.raw_decode(text, bracket.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    raise _CallFailed("answered with no readable array")
