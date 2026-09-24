#!/bin/sh
# Runs the consumer's installed `filepawl hook` on the PreToolUse payload.
# Prefers the project venv, falls back to PATH, and is silent when neither
# exists. Always exits 0: a PreToolUse hook that exits 2 blocks the edit,
# and this hook blocks only through the JSON filepawl prints, never through
# a failure (docs/design.md §7.1).

bin="${CLAUDE_PROJECT_DIR:-.}/.venv/bin/filepawl"
if [ ! -x "$bin" ]; then
    bin=$(command -v filepawl) || exit 0
fi
"$bin" hook 2>/dev/null
exit 0
