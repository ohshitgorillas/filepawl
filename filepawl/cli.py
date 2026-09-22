"""Command-line entry point: `check`, `accept`, `init` (design.md §6.4, §7).

Every failure path routes through `FilepawlError`, which `main` prints to
stderr as `filepawl: <message>` and turns into exit 2. Findings are
collected from every discovered gate, printed `path: message` sorted by
`(path, message)`, and followed by the exact `filepawl accept` command
whenever any finding says it is fixable that way.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import TextIO

from filepawl.config import DEFAULT_POLICY_STUB, KNOWN_MOVERS, Policy, load_policy
from filepawl.errors import ConfigError, FilepawlError
from filepawl.gates.base import Finding, Gate
from filepawl.gates.registry import discover_gates
from filepawl.state import STATE_FILE, Entry, State, load_state, write_state
from filepawl.tree import Tree, build_tree, find_root

_MOVER_ENTRY_POINT_GROUP = "filepawl.movers"
_PYPROJECT = "pyproject.toml"
# A wholly commented stub leaves `[tool.filepawl]` absent, so the TOML
# check alone would append it again on a second `init`; this marker line
# makes the append idempotent on the text as well.
_STUB_MARKER = "# [tool.filepawl]"


@dataclass(frozen=True)
class _Run:
    """One resolved invocation: root, policy, tree, state and gates."""

    root: Path
    policy: Policy
    tree: Tree
    state: State
    gates: list[Gate]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="filepawl")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="report findings over the tree")
    check.add_argument("paths", nargs="*", help="narrow the measured set")

    accept = subparsers.add_parser("accept", help="add, lower or drop allowances")
    accept.add_argument("paths", nargs="*", help="narrow the measured set")
    accept.add_argument("--reason", help="reason for the one path given")

    subparsers.add_parser("init", help="write state and a commented policy stub")

    mover = subparsers.add_parser("mv", help="move a file and rewrite imports")
    mover.add_argument("old", nargs="?")
    mover.add_argument("new", nargs="?")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            return _check(args.paths)
        if args.command == "accept":
            return _accept(args.paths, args.reason)
        if args.command == "init":
            return _init()
        if args.command == "mv":
            print("mv: not implemented", file=sys.stderr)
            return 2
    except FilepawlError as exc:
        print(f"filepawl: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 2


# --- commands ----------------------------------------------------------


def _check(paths: list[str]) -> int:
    run = _prepare(paths)
    return _report(_findings(run, run.state), run.tree, sys.stdout)


def _accept(paths: list[str], reason: str | None) -> int:
    if reason is not None and len(paths) != 1:
        raise FilepawlError("--reason takes exactly one path")

    run = _prepare(paths)
    state = run.state
    for gate in run.gates:
        state = gate.accept(run.tree, run.policy, state)
    if reason is not None:
        state = _with_reason(state, _relative(run.root, paths)[0], reason)
    if state != run.state:
        write_state(run.root, state)

    return _report(_findings(run, state), run.tree, sys.stdout)


def _init() -> int:
    root = find_root(Path.cwd())
    if (root / STATE_FILE).exists():
        raise FilepawlError(f"{STATE_FILE} already exists; refusing to overwrite")

    policy = load_policy(root)
    _check_movers(policy)
    tree = build_tree(root, policy, None)

    state = State()
    for gate in discover_gates(policy):
        state = gate.accept(tree, policy, state)
    write_state(root, state)

    _append_stub(root)
    return 0


# --- shared machinery --------------------------------------------------


def _prepare(paths: list[str]) -> _Run:
    root = find_root(Path.cwd())
    policy = load_policy(root)
    _check_movers(policy)
    selected = _relative(root, paths) if paths else None
    if selected is not None and "." in selected:
        # A path naming the root itself narrows nothing.
        selected = None
    return _Run(
        root=root,
        policy=policy,
        tree=build_tree(root, policy, selected),
        state=load_state(root),
        gates=discover_gates(policy),
    )


def _relative(root: Path, paths: list[str]) -> list[str]:
    """Normalize argv paths, which are relative to the cwd, against `root`."""
    resolved = root.resolve()
    out: list[str] = []
    for raw in paths:
        candidate = (Path.cwd() / raw).resolve()
        try:
            out.append(candidate.relative_to(resolved).as_posix())
        except ValueError:
            raise ConfigError(f"{raw}: outside the repository at {root}") from None
    return out


def _check_movers(policy: Policy) -> None:
    """Reject a `mover` name that is neither built in nor an entry point.

    `config.py` passes an unknown name through as a string because it
    cannot see third-party movers; §4 makes it exit 2, so the check lands
    here, where the entry-point group is readable.
    """
    installed: set[str] | None = None
    for language, language_policy in policy.languages.items():
        mover = language_policy.mover
        if mover is None or mover in KNOWN_MOVERS:
            continue
        if installed is None:
            installed = {ep.name for ep in entry_points(group=_MOVER_ENTRY_POINT_GROUP)}
        if mover not in installed:
            raise ConfigError(f"unknown mover {mover!r} in [tool.filepawl.{language}]")


def _findings(run: _Run, state: State) -> list[Finding]:
    findings: list[Finding] = []
    for gate in run.gates:
        findings += gate.run(run.tree, run.policy, state)
    return findings


def _report(findings: list[Finding], tree: Tree, stream: TextIO) -> int:
    for finding in sorted(findings, key=lambda f: (f.path, f.message)):
        print(f"{finding.path}: {finding.message}", file=stream)
    if any(finding.fixable_by_accept for finding in findings):
        fixable = sorted(
            {
                finding.path
                for finding in findings
                if finding.fixable_by_accept and _in_tree(tree, finding.path)
            }
        )
        print(" ".join(["filepawl", "accept", *fixable]), file=stream)
    return 1 if findings else 0


def _in_tree(tree: Tree, path: str) -> bool:
    """Whether a path can be named on an `accept` command line.

    A stale entry whose file is gone is fixable but not nameable, so it
    drops out of the printed command and `filepawl accept` stands bare.
    """
    return path in tree.files and (tree.root / path).is_file()


def _with_reason(state: State, path: str, reason: str) -> State:
    entry = state.allowance.get(path)
    if entry is None:
        raise FilepawlError(
            f"{path}: no allowance entry; nothing to attach a reason to"
        )
    allowance = dict(state.allowance)
    allowance[path] = Entry(lines=entry.lines, reason=reason)
    return State(version=state.version, allowance=allowance)


def _append_stub(root: Path) -> None:
    """Append the commented policy stub to `pyproject.toml`, once."""
    path = root / _PYPROJECT
    if not path.is_file():
        path.write_text(DEFAULT_POLICY_STUB.lstrip("\n"), encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"unparseable {_PYPROJECT}: {exc}") from exc
    tool = data.get("tool")
    if isinstance(tool, dict) and "filepawl" in tool:
        return
    if _STUB_MARKER in text:
        return

    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + DEFAULT_POLICY_STUB, encoding="utf-8")
