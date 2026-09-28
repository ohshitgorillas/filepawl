"""Port of Trivia Judge's nesting-gate tests to filepawl's nesting gate.

Source: ``~/dev/triviajudge/tests/gates/test_check_nesting.py``. Each test
cites the source test it ports; parametrized rows keep the source's rows in
the source's order. The source pins ``depths`` directly; here each measured
depth is read back from the finding the gate prints at a limit one below the
shallowest function in the module, so every function is reported with its
depth. The source's def line is not part of a filepawl finding and is not
ported. The source's ``EXEMPT`` table is expressed as ``NestingPolicy.exempt``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_code import NestingPolicy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import NestingGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

FLAT = """
def f():
    pass
"""

ONE_BLOCK = """
def f():
    if a:
        pass
"""

FOUR_DEEP = """
def f():
    if a:
        for b in c:
            while d:
                with e:
                    pass
"""

FIVE_DEEP = """
def f():
    if a:
        for b in c:
            while d:
                with e:
                    if g:
                        pass
"""

ELIF_CHAIN = """
def f():
    if a:
        pass
    elif b:
        pass
    elif c:
        pass
    else:
        pass
"""

ELSE_HOLDING_AN_IF = """
def f():
    if a:
        pass
    else:
        if b:
            pass
"""

HANDLER_BODY = """
def f():
    try:
        pass
    except ValueError:
        if a:
            pass
"""

FINALLY_BODY = """
def f():
    try:
        pass
    finally:
        if a:
            pass
"""

EXCEPT_STAR = """
def f():
    try:
        pass
    except* ValueError:
        pass
"""

MATCH_CASE = """
def f():
    match a:
        case 1:
            if b:
                pass
"""

ASYNC_BLOCKS = """
async def f():
    async with a:
        async for b in c:
            pass
"""

NESTED_DEF = """
def outer():
    if a:
        def inner():
            if b:
                if c:
                    if d:
                        if e:
                            pass
"""

METHOD = """
class Holder:
    def method(self):
        if a:
            pass
"""

NESTED_CLASS = """
class Outer:
    class Inner:
        def method(self):
            pass
"""

#: Where a depth case writes its module.
MOD = "pkg/mod.py"

#: Where a refusal case writes its module, and the reason an exemption carries.
DEEP = "pkg/deep.py"
SHALLOW = "pkg/shallow.py"
GONE = "pkg/gone.py"
NAMED = "pkg/named.py"
REASON = "the arms are one decision"

#: A file with no function, so a tree needing no module of its own under test
#: still has a commit.
FILLER = ("pkg/filler.py", "NAME = 1\n")

POLICY_FILE = "pyproject.toml"


def _deep(depth: int, limit: int = 4) -> str:
    return f"nests {depth} deep (max {limit}) — flatten the function"


def _stale(key: str, message: str) -> Finding:
    return Finding(POLICY_FILE, f"[tool.filepawl.nesting.exempt] {key!r}: {message}")


def _run(
    root: Path, *, max_depth: int = 4, exempt: Mapping[str, str] = MappingProxyType({})
) -> list[Finding]:
    nesting = NestingPolicy(max_depth=max_depth, exempt=dict(exempt))
    policy: Policy = dataclasses.replace(default_policy(), nesting=nesting)
    return NestingGate().run(build_tree(root, policy), policy, State())


def _measured(root: Path, found: list[tuple[str, int]]) -> None:
    """Assert the gate reports exactly `found`, at a limit exposing every depth."""
    limit = min(depth for _, depth in found) - 1
    expected = [Finding(f"{MOD}::{name}", _deep(depth, limit)) for name, depth in found]
    assert _run(root, max_depth=limit) == sorted(expected)


# --- behavior 1: a level is a block, and two shapes deliberately are not ------


@pytest.mark.parametrize(
    ("source", "found"),
    [
        (FLAT, [("f", 0)]),
        (ONE_BLOCK, [("f", 1)]),
        (FOUR_DEEP, [("f", 4)]),
        (FIVE_DEEP, [("f", 5)]),
        (ELIF_CHAIN, [("f", 1)]),
        (ELSE_HOLDING_AN_IF, [("f", 2)]),
        (HANDLER_BODY, [("f", 2)]),
        (FINALLY_BODY, [("f", 2)]),
        (EXCEPT_STAR, [("f", 1)]),
        (MATCH_CASE, [("f", 2)]),
        (ASYNC_BLOCKS, [("f", 2)]),
    ],
)
def test_the_measured_depth_is_the_number_of_blocks_a_line_sits_inside(
    repo: RepoFactory, source: str, found: list[tuple[str, int]]
) -> None:
    """Port of `test_the_measured_depth_is_the_number_of_blocks_a_line_sits_inside`."""
    _measured(repo({MOD: source}), found)


# --- behavior 2: a function is named where the reader finds it ----------------


@pytest.mark.parametrize(
    ("source", "found"),
    [
        (NESTED_DEF, [("outer", 1), ("outer.inner", 4)]),
        (METHOD, [("Holder.method", 1)]),
        (NESTED_CLASS, [("Outer.Inner.method", 0)]),
    ],
)
def test_a_function_is_reported_under_its_dotted_name_and_measured_on_its_own(
    repo: RepoFactory, source: str, found: list[tuple[str, int]]
) -> None:
    """Port of `test_a_function_is_reported_under_its_dotted_name_and_measured_on_its_own`."""  # noqa: E501
    _measured(repo({MOD: source}), found)


# --- behavior 3: past the limit a site fails unless an exemption says why -----


def test_a_function_at_the_limit_passes_without_a_word(repo: RepoFactory) -> None:
    """Port of `test_a_function_at_the_limit_passes_without_a_word`."""
    root = repo({DEEP: FOUR_DEEP})
    at_limit = _run(root)
    under_limit = _run(root, max_depth=3)
    assert (at_limit, under_limit) == ([], [Finding(f"{DEEP}::f", _deep(4, 3))])


def test_a_deep_function_is_refused_by_file_line_name_and_depth(
    repo: RepoFactory,
) -> None:
    """Port of `test_a_deep_function_is_refused_by_file_line_name_and_depth`.

    A filepawl finding names the function by path and qualified name; the
    source's line number is not part of it.
    """
    assert _run(repo({DEEP: FIVE_DEEP})) == [Finding(f"{DEEP}::f", _deep(5))]


def test_an_exemption_on_the_site_itself_silences_the_refusal(
    repo: RepoFactory,
) -> None:
    """Port of `test_an_exemption_on_the_site_itself_silences_the_refusal`."""
    root = repo({DEEP: FIVE_DEEP})
    plain = _run(root)
    exempt = _run(root, exempt={f"{DEEP}::f": REASON})
    assert (plain, exempt) == ([Finding(f"{DEEP}::f", _deep(5))], [])


# --- behavior 4: an exemption is audited off the filesystem -------------------


def test_an_exemption_still_excusing_a_deep_site_is_silent_though_argv_is_empty(
    repo: RepoFactory,
) -> None:
    """Port of `test_an_exemption_still_excusing_a_deep_site_is_silent_though_argv_is_empty`.

    The nesting gate always runs over the whole tree, so there is no argv to
    leave empty; the audit is the same.
    """  # noqa: E501
    root = repo({DEEP: FIVE_DEEP})
    plain = _run(root)
    exempt = _run(root, exempt={f"{DEEP}::f": REASON})
    assert (plain, exempt) == ([Finding(f"{DEEP}::f", _deep(5))], [])


def test_an_exemption_naming_no_file_is_refused_by_its_key(
    repo: RepoFactory,
) -> None:
    """Port of `test_an_exemption_naming_no_file_is_refused_by_its_key`.

    The source writes no file at all; a git tree needs one commit, so this
    tree carries a filler module with no function.
    """
    key = f"{GONE}::f"
    root = repo(dict([FILLER]))
    assert _run(root, exempt={key: REASON}) == [_stale(key, "names no file")]


def test_an_exemption_naming_no_function_in_its_file_is_refused_by_its_key(
    repo: RepoFactory,
) -> None:
    """Port of `test_an_exemption_naming_no_function_in_its_file_is_refused_by_its_key`.

    The source leaves argv empty so `deep.py::f` is not measured; the gate
    here runs over the whole tree, so that function is refused as well.
    """  # noqa: E501
    key = f"{DEEP}::missing"
    root = repo({DEEP: FIVE_DEEP})
    assert _run(root, exempt={key: REASON}) == [
        Finding(f"{DEEP}::f", _deep(5)),
        _stale(key, "names no function"),
    ]


def test_an_exemption_on_a_site_within_the_limit_is_refused_with_its_depth(
    repo: RepoFactory,
) -> None:
    """Port of `test_an_exemption_on_a_site_within_the_limit_is_refused_with_its_depth`."""  # noqa: E501
    key = f"{SHALLOW}::f"
    root = repo({SHALLOW: ONE_BLOCK})
    assert _run(root, exempt={key: REASON}) == [
        _stale(key, "nests 1 deep, within the limit of 4")
    ]


# --- behavior 5: the files a run names are checked ----------------------------


def test_the_command_line_checks_the_files_it_names(repo: RepoFactory) -> None:
    """Port of `test_the_command_line_checks_the_files_it_names`.

    The finding is ported; the printed layout, summary line and exit code
    belong to the source script's command line and are not.
    """
    assert _run(repo({NAMED: FIVE_DEEP})) == [Finding(f"{NAMED}::f", _deep(5))]
