"""The `judge` command: policy, cases, calls and report (design.md §7.2).

Opt-in through `[tool.filepawl.judge] enabled`. Each dodge prints one line,
sorted by key, beside the audit of `[tool.filepawl.judge.exempt]`; the run
exits 1 when either has something to say. A `JudgeError` or configuration
error reaches `cli.main`, which exits 2.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TextIO

from filepawl.config import Policy, load_policy
from filepawl.gates.base import Finding
from filepawl.gates.handlers import function_returns
from filepawl.judge.cases import find_cases
from filepawl.judge.transport import ask_judge
from filepawl.tree import build_tree, find_root

INNER = "FILEPAWL_JUDGE_INNER"
_POLICY_FILE = "pyproject.toml"
_WHERE = "[tool.filepawl.judge.exempt]"
_FIX = "fix it on a route the gate traces, or exempt it with a reason"


def run_judge(head: bool, stdout: TextIO) -> int:
    if INNER in os.environ:
        # The model's own session runs hooks too; a judge there would start
        # a second judge.
        return 0
    root = find_root(Path.cwd())
    policy = load_policy(root)
    if not policy.judge.enabled:
        return 0
    findings = _audit(root, policy)
    cases = find_cases(root, policy, head)
    if cases:
        findings += [
            Finding(
                verdict.case.key,
                f"{verdict.case.gate} judge: {verdict.reason} — {_FIX}",
            )
            for verdict in ask_judge(root, cases, policy.judge)
            if verdict.verdict == "dodge"
        ]
    for finding in sorted(findings):
        print(f"{finding.path}: {finding.message}", file=stdout)
    return 1 if findings else 0


def _audit(root: Path, policy: Policy) -> list[Finding]:
    """Report each exemption entry that names no Python file or no function."""
    exempt = policy.judge.exempt
    files = {path for path in build_tree(root, policy).files if path.endswith(".py")}
    defined: dict[str, set[str]] = {}
    for path in sorted({key.partition("::")[0] for key in exempt} & files):
        try:
            text = (root / path).read_text(encoding="utf-8")
            module = ast.parse(text, filename=path)
        except (SyntaxError, UnicodeDecodeError):
            # A file that does not parse defines no function an entry can name.
            continue
        defined[path] = {name for name, _ in function_returns(module)}
    findings: list[Finding] = []
    for key in sorted(exempt):
        path, _, func = key.partition("::")
        if path not in files:
            message = "names no file"
        elif func not in defined.get(path, set()):
            message = "names no function"
        else:
            continue
        findings.append(Finding(_POLICY_FILE, f"{_WHERE} {key!r}: {message}"))
    return findings
