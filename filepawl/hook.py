"""The `hook` command: an edit-time notice for Claude Code (docs/design.md §7.1).

Reads one `PreToolUse` payload on stdin and projects the edited file's
length after the edit. An edit that grows a non-exempt file to over its cap
is denied; any other edit that leaves the file in the ratchet or over a cap
gets a notice. Every path, malformed input and configuration errors
included, returns 0, and anything the hook cannot judge is silent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from filepawl.config import Policy, load_policy
from filepawl.errors import FilepawlError
from filepawl.state import Entry, load_state
from filepawl.tree import find_root, glob_match

_TOOLS = ("Write", "Edit", "MultiEdit")
_DELEGATE = "Plan the split now; it is mechanical and can be delegated."


@dataclass(frozen=True)
class _Verdict:
    text: str
    deny: bool = False


class _Unjudgeable(Exception):
    """The payload, the repository or the file cannot be read."""


def run_hook(stdin: TextIO, stdout: TextIO) -> int:
    try:
        verdict = _verdict(stdin.read())
    except _Unjudgeable:
        # Silence is the whole handling: `check` reports configuration
        # errors, and Claude Code reports a failed edit.
        pass
    else:
        if verdict is not None:
            _emit(verdict, stdout)
    return 0


def _emit(verdict: _Verdict, stdout: TextIO) -> None:
    specific: dict[str, str] = {"hookEventName": "PreToolUse"}
    if verdict.deny:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = f"filepawl: {verdict.text}"
    else:
        specific["additionalContext"] = f"filepawl: {verdict.text}"
    output = {"hookSpecificOutput": specific}
    print(json.dumps(output, ensure_ascii=False), file=stdout)


def _verdict(raw: str) -> _Verdict | None:
    """Return the notice or denial for an edit, or None when it earns neither.

    Raises `_Unjudgeable` when the payload, the repository or the file
    cannot be read.
    """
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise _Unjudgeable from exc
    if not isinstance(payload, dict) or payload.get("tool_name") not in _TOOLS:
        return None
    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input")
    if not isinstance(cwd, str) or not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str):
        return None

    try:
        root = find_root(Path(cwd))
        policy = load_policy(root)
        state = load_state(root)
    except (FilepawlError, OSError) as exc:
        raise _Unjudgeable from exc
    if not policy.length.enabled:
        return None

    target = (Path(cwd) / file_path).resolve()
    if not target.is_relative_to(root.resolve()):
        return None
    path = target.relative_to(root.resolve()).as_posix()
    if not _included(policy, path):
        return None

    try:
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
    except (OSError, UnicodeDecodeError) as exc:
        raise _Unjudgeable from exc
    after = _project(str(payload["tool_name"]), tool_input, before)
    if after is None:
        return None

    return _judge(path, policy, state.allowance, len(before.splitlines()), after)


def _included(policy: Policy, path: str) -> bool:
    return any(
        glob_match(pattern, path)
        for language in policy.languages.values()
        for pattern in language.include
    )


def _project(tool: str, tool_input: dict[str, object], text: str) -> int | None:
    """The file's length after the edit, or None when it cannot be projected."""
    if tool == "Write":
        content = tool_input.get("content")
        return len(content.splitlines()) if isinstance(content, str) else None
    edits = [tool_input] if tool == "Edit" else tool_input.get("edits")
    if not isinstance(edits, list):
        return None
    for edit in edits:
        replaced = _apply(edit, text)
        if replaced is None:
            return None
        text = replaced
    return len(text.splitlines())


def _apply(edit: object, text: str) -> str | None:
    if not isinstance(edit, dict):
        return None
    old = edit.get("old_string")
    new = edit.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str) or old not in text:
        return None
    count = -1 if edit.get("replace_all") is True else 1
    return text.replace(old, new, count)


def _judge(
    path: str, policy: Policy, allowance: dict[str, Entry], before: int, after: int
) -> _Verdict | None:
    length = policy.length
    is_test = any(glob_match(pattern, path) for pattern in policy.tests)
    exempt = path in policy.exempt
    cap = length.cap_tests if is_test else length.cap
    if not exempt and after > cap and after > before:
        return _Verdict(
            text=(
                f"{path}: this edit takes it {before} → {after} lines, over cap "
                f"{cap}; blocked. Split the file first; the split is mechanical "
                "and can be delegated."
            ),
            deny=True,
        )

    if is_test:
        if exempt or after <= cap:
            return None
        return _Verdict(
            f"{path}: test file goes {before} → {after} lines, over cap "
            f"{cap}; split it before committing."
        )

    message = _ratchet_message(path, policy, allowance, before, after)
    return None if message is None else _Verdict(message)


def _ratchet_message(
    path: str, policy: Policy, allowance: dict[str, Entry], before: int, after: int
) -> str | None:
    length = policy.length
    if after <= length.watch:
        return None
    entry = allowance.get(path)
    if entry is not None:
        lines = entry.lines
        parts = [
            f"{path}: in the length ratchet at {lines} lines; this edit takes it "
            f"{before} → {after}."
        ]
        if after > lines:
            parts.append(
                f"{after - lines} lines over the allowance; split them out "
                "before committing."
            )
        else:
            parts.append(f"It may shrink, never grow past {lines}.")
    else:
        parts = [
            f"{path}: goes {before} → {after} lines, over watch line "
            f"{length.watch}; it enters the length ratchet on the next "
            "`filepawl accept` and may only shrink after that."
        ]
    if after > length.cap and path not in policy.exempt:
        parts.append(f"Over cap {length.cap}; split it before committing.")
    parts.append(_DELEGATE)
    return " ".join(parts)
