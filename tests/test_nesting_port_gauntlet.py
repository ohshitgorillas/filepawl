"""Port of Gauntlet's nesting-gate self-test to filepawl's nesting gate.

Source: ``~/dev/gauntlet/scripts/gates/code/nesting_selftest.py``. Each test
cites the ``check(...)`` rule strings it ports; where the source checks a
status and a stdout line from one run, the port asserts the findings of that
run once. The source hands its gate an exemption mapping, which is expressed
here as ``NestingPolicy.exempt``. The gate runs over the whole tree (design.md
§6.3), so the source's named file set is the tree it builds.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import NestingPolicy, Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import NestingGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

#: Each block-opening construct as (opening lines, how far its body is
#: indented past the opener, lines that close it off), as in the source.
BLOCKS: dict[str, tuple[list[str], int, list[str]]] = {
    "if": (["if cond:"], 1, []),
    "for": (["for _item in items:"], 1, []),
    "while": (["while cond:"], 1, []),
    "with": (["with ctx:"], 1, []),
    "try": (["try:"], 1, ["except Exception:", "    pass"]),
    "match": (["match value:", "    case _:"], 2, []),
}

#: An if/elif chain three levels in; every arm shares its ``if``'s level.
ELIF_CHAIN = """
def f():
    if cond:
        for _item in items:
            if a:
                pass
            elif b:
                pass
            else:
                pass
"""

#: A nested function five deep inside an outer one only two deep.
NESTED_DEF_OVER_LIMIT = """
def outer():
    if cond:

        def inner():
            if cond:
                for _item in items:
                    while cond:
                        with ctx:
                            if cond:
                                pass
"""

POLICY_FILE = "pyproject.toml"
STALE = "[tool.filepawl.nesting.exempt] {!r}: {}"

DEEP = "hooks/deep.py"


def _nest(kind: str, depth: int, indent: int = 1) -> list[str]:
    opener, step, trailer = BLOCKS[kind]
    pad = "    " * indent
    lines = [pad + line for line in opener]
    if depth > 1:
        lines += _nest(kind, depth - 1, indent + step)
    else:
        lines.append("    " * (indent + step) + "pass")
    return lines + [pad + line for line in trailer]


def _function(kind: str, depth: int, name: str = "f") -> str:
    return "\n".join([f"def {name}():", *_nest(kind, depth)]) + "\n"


def _deep(depth: int) -> str:
    return f"nests {depth} deep (max 4) — flatten the function"


def _run(
    files: dict[str, str | int],
    repo: RepoFactory,
    *,
    exempt: dict[str, str] | None = None,
) -> list[Finding]:
    root = repo(files)
    nesting = NestingPolicy(exempt=exempt or {})
    policy: Policy = dataclasses.replace(default_policy(), nesting=nesting)
    return NestingGate().run(build_tree(root, policy), policy, State())


def test_function_at_the_limit_passes(repo: RepoFactory) -> None:
    """Port of "a function at the limit passes"."""
    assert _run({DEEP: _function("if", 4)}, repo) == []


def test_function_one_past_the_limit_fails_and_is_named(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one over-limit run.

    "a function one past the limit fails", "the offending file is named on
    stdout" and "the reported depth is on stdout".
    """
    assert _run({DEEP: _function("if", 5)}, repo) == [Finding(f"{DEEP}::f", _deep(5))]


def test_elif_chain_shares_its_ifs_level(repo: RepoFactory) -> None:
    """Port of "an elif chain shares its if's level and passes"."""
    assert _run({DEEP: ELIF_CHAIN}, repo) == []


def test_nested_def_over_the_limit_fails_under_its_dotted_name(
    repo: RepoFactory,
) -> None:
    """Port of the self-test's rules for one nested-def run.

    "a nested def over the limit fails" and "it is reported under its dotted
    name". The source prints ``outer.inner()``; filepawl names it
    ``path::outer.inner`` per design.md §6.7.
    """
    assert _run({DEEP: NESTED_DEF_OVER_LIMIT}, repo) == [
        Finding(f"{DEEP}::outer.inner", _deep(5))
    ]


def test_exempt_function_passes(repo: RepoFactory) -> None:
    """Port of "an exempt function passes"."""
    exempt = {f"{DEEP}::f": "measured on purpose"}
    assert _run({DEEP: _function("if", 5)}, repo, exempt=exempt) == []


def test_exemption_for_function_within_the_limit_is_stale(
    repo: RepoFactory,
) -> None:
    """Port of the self-test's rules for one within-limit exemption run.

    "an exemption for a function back within the limit fails as stale" and
    "the stale entry is named on stdout".
    """
    key = f"{DEEP}::f"
    assert _run({DEEP: _function("if", 4)}, repo, exempt={key: "no longer needed"}) == [
        Finding(POLICY_FILE, STALE.format(key, "nests 4 deep, within the limit of 4"))
    ]


def test_exemption_naming_no_file_is_stale(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one missing-file exemption run.

    "an exemption naming no file fails as stale" and "the missing-file entry
    is named on stdout".
    """
    key = "hooks/missing.py::f"
    assert _run({DEEP: _function("if", 4)}, repo, exempt={key: "long gone"}) == [
        Finding(POLICY_FILE, STALE.format(key, "names no file"))
    ]


def test_one_offender_among_compliant_files_fails_alone(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one mixed-tree run.

    "one offender among compliant files fails the gate" and "the compliant
    file is not named".
    """
    files: dict[str, str | int] = {
        "hooks/one.py": _function("if", 5, "f"),
        "hooks/two.py": _function("if", 4, "f"),
    }
    assert _run(files, repo) == [Finding("hooks/one.py::f", _deep(5))]
