"""The `hook` command: an edit-time notice for Claude Code (docs/design.md §7.1).

Reads one `PreToolUse` payload on stdin, projects the edited file's length
after the edit, and prints a notice as hook JSON when that length puts the
file in the ratchet or over a cap. It advises and never blocks: every path,
malformed input and configuration errors included, returns 0, and anything
it cannot judge is silent. `check` stays the gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from filepawl.config import Policy, load_policy
from filepawl.errors import FilepawlError
from filepawl.state import Entry, load_state
from filepawl.tree import find_root, glob_match

_TOOLS = ("Write", "Edit", "MultiEdit")
_DELEGATE = "Plan the split now; it is mechanical and can be delegated."


def run_hook(stdin: TextIO, stdout: TextIO) -> int:
    notice = _notice(stdin.read())
    if notice is not None:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"filepawl: {notice}",
            }
        }
        print(json.dumps(output, ensure_ascii=False), file=stdout)
    return 0


def _notice(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
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
    except (FilepawlError, OSError):
        return None
    if not policy.length.enabled:
        return None

    target = (Path(cwd) / file_path).resolve()
    try:
        path = target.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    if not _included(policy, path):
        return None

    try:
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return None
    after = _project(str(payload["tool_name"]), tool_input, before)
    if after is None:
        return None

    return _message(path, policy, state.allowance, len(before.splitlines()), after)


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


def _message(
    path: str, policy: Policy, allowance: dict[str, Entry], before: int, after: int
) -> str | None:
    length = policy.length
    is_test = any(glob_match(pattern, path) for pattern in policy.tests)
    if is_test:
        if after <= length.cap_tests:
            return None
        return (
            f"{path}: test file goes {before} → {after} lines, over cap "
            f"{length.cap_tests}; split it before committing."
        )

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
