"""HQPTuner's nesting suite, ported onto filepawl's nesting gate.

Source: `~/dev/hqptuner/tests/gates/test_nesting.py`. Each test cites the
source test it ports. HQPTuner's `EXEMPT` mapping becomes `NestingPolicy.exempt`.
Cases on its `depths` seam become findings at a `max_depth` that exposes the
measured depth. "Named on stdout" becomes a finding whose path or message
carries the name; "one line" becomes one finding.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_code import NestingPolicy
from filepawl.gates.base import Finding
from filepawl.gates.nesting import NestingGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

#: Each block-opening construct as (opening lines, how far its body is indented
#: past the opener, lines that close it off).
BLOCKS: dict[str, tuple[list[str], int, list[str]]] = {
    "if": (["if cond:"], 1, []),
    "for": (["for _item in items:"], 1, []),
    "while": (["while cond:"], 1, []),
    "with": (["with ctx:"], 1, []),
    "try": (["try:"], 1, ["except Exception:", "    pass"]),
    "match": (["match value:", "    case _:"], 2, []),
    "async for": (["async for _item in items:"], 1, []),
    "async with": (["async with ctx:"], 1, []),
}

ASYNC_BLOCKS = ["async for", "async with"]
SYNC_BLOCKS = ["if", "for", "while", "with", "try", "match"]

WHY = "the parser walks a nested document"


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
    header = f"async def {name}():" if kind in ASYNC_BLOCKS else f"def {name}():"
    return "\n".join([header, *_nest(kind, depth)]) + "\n"


DEEP_METHOD = """
class Tuner:
    def set_volume(self, level):
        if cond:
            for _item in items:
                while cond:
                    with ctx:
                        if level:
                            pass
"""

NESTED_DEF_WITHIN_LIMIT = """
def outer():
    if cond:
        for _item in items:
            while cond:
                def inner():
                    if cond:
                        for _other in items:
                            while cond:
                                pass
"""

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

ELIF_CHAIN_THREE_DEEP = """
def f():
    if cond:
        for _item in items:
            if a:
                pass
            elif b:
                pass
            elif c:
                pass
            elif d:
                pass
            else:
                pass
"""

ELSE_HOLDING_AN_IF = """
def f():
    if cond:
        for _item in items:
            if a:
                pass
            else:
                if b:
                    if c:
                        pass
"""

THREE_VIOLATIONS = """
def one():
    if cond:
        for _item in items:
            while cond:
                with ctx:
                    if cond:
                        pass


def two():
    for _item in items:
        for _other in items:
            for _third in items:
                for _fourth in items:
                    for _fifth in items:
                        pass


def three():
    while cond:
        while cond:
            while cond:
                while cond:
                    while cond:
                        pass
"""

FLAT = """
def f(level):
    total = level + 1
    return total
"""


def _policy(exempt: dict[str, str] | None = None, max_depth: int = 4) -> Policy:
    nesting = NestingPolicy(max_depth=max_depth, exempt=exempt or {})
    return dataclasses.replace(default_policy(), nesting=nesting)


def _run(root: Path, policy: Policy, paths: list[str] | None = None) -> list[Finding]:
    return NestingGate().run(build_tree(root, policy, paths), policy, State())


def _deep(key: str, depth: int, limit: int = 4) -> Finding:
    return Finding(key, f"nests {depth} deep (max {limit}) — flatten the function")


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.nesting.exempt] {key!r}: {message}"
    )


def _named(findings: list[Finding], needle: str) -> bool:
    return any(needle in f.path or needle in f.message for f in findings)


# --- depth counting ------------------------------------------------------------


def test_function_at_the_limit_passes(repo: RepoFactory) -> None:
    """Port of test_a_function_at_the_limit_passes."""
    root = repo({"hqptuner/core/deep.py": _function("if", 4)})
    at_limit = _run(root, _policy())
    under_limit = _run(root, _policy(max_depth=3))
    assert (at_limit, under_limit) == (
        [],
        [_deep("hqptuner/core/deep.py::f", 4, limit=3)],
    )


def test_function_at_the_limit_reports_nothing(repo: RepoFactory) -> None:
    """Port of test_a_function_at_the_limit_prints_nothing."""
    root = repo({"hqptuner/core/deep.py": _function("if", 4)})
    at_limit = _run(root, _policy())
    under_limit = _run(root, _policy(max_depth=3))
    assert (len(at_limit), len(under_limit)) == (0, 1)


def test_flat_module_passes(repo: RepoFactory) -> None:
    """Port of test_a_flat_module_passes."""
    # A limit below zero exposes every function, even one that nests nothing.
    root = repo({"hqptuner/core/flat.py": FLAT})
    at_four = _run(root, _policy())
    below_zero = _run(root, _policy(max_depth=-1))
    assert (at_four, below_zero) == (
        [],
        [_deep("hqptuner/core/flat.py::f", 0, limit=-1)],
    )


def test_function_one_past_the_limit_fails(repo: RepoFactory) -> None:
    """Port of test_a_function_one_past_the_limit_fails."""
    root = repo({"hqptuner/core/deep.py": _function("if", 5)})
    assert _run(root, _policy()) == [_deep("hqptuner/core/deep.py::f", 5)]


# --- what counts as a level ----------------------------------------------------


@pytest.mark.parametrize("kind", SYNC_BLOCKS)
def test_each_block_construct_at_the_limit_passes(repo: RepoFactory, kind: str) -> None:
    """Port of test_each_block_construct_counts_as_one_level_at_the_limit."""
    root = repo({"hqptuner/core/deep.py": _function(kind, 4)})
    at_limit = _run(root, _policy())
    under_limit = _run(root, _policy(max_depth=3))
    assert (at_limit, under_limit) == (
        [],
        [_deep("hqptuner/core/deep.py::f", 4, limit=3)],
    )


@pytest.mark.parametrize("kind", SYNC_BLOCKS)
def test_each_block_construct_past_the_limit_fails(
    repo: RepoFactory, kind: str
) -> None:
    """Port of test_each_block_construct_counts_as_one_level_past_the_limit."""
    root = repo({"hqptuner/core/deep.py": _function(kind, 5)})
    assert _run(root, _policy()) == [_deep("hqptuner/core/deep.py::f", 5)]


@pytest.mark.parametrize("kind", ASYNC_BLOCKS)
def test_async_construct_at_the_limit_passes(repo: RepoFactory, kind: str) -> None:
    """Port of test_an_async_construct_at_the_limit_passes_like_its_sync_form."""
    root = repo({"hqptuner/core/deep.py": _function(kind, 4)})
    at_limit = _run(root, _policy())
    under_limit = _run(root, _policy(max_depth=3))
    assert (at_limit, under_limit) == (
        [],
        [_deep("hqptuner/core/deep.py::f", 4, limit=3)],
    )


@pytest.mark.parametrize("kind", ASYNC_BLOCKS)
def test_async_construct_past_the_limit_fails(repo: RepoFactory, kind: str) -> None:
    """Port of test_an_async_construct_past_the_limit_fails_like_its_sync_form."""
    root = repo({"hqptuner/core/deep.py": _function(kind, 5)})
    assert _run(root, _policy()) == [_deep("hqptuner/core/deep.py::f", 5)]


def test_async_function_over_the_limit_is_named(repo: RepoFactory) -> None:
    """Port of test_an_async_function_over_the_limit_is_named_on_stdout."""
    root = repo({"hqptuner/core/deep.py": _function("async for", 5)})
    assert _named(_run(root, _policy()), "hqptuner/core/deep.py::f")


def test_elif_chain_shares_a_level_with_its_if(repo: RepoFactory) -> None:
    """Port of test_an_elif_chain_shares_a_level_with_its_if."""
    root = repo({"hqptuner/core/chain.py": ELIF_CHAIN_THREE_DEEP})
    at_four = _run(root, _policy())
    at_two = _run(root, _policy(max_depth=2))
    assert (at_four, at_two) == ([], [_deep("hqptuner/core/chain.py::f", 3, limit=2)])


def test_plain_else_holding_an_if_adds_a_level(repo: RepoFactory) -> None:
    """Port of test_a_plain_else_holding_an_if_adds_a_level."""
    root = repo({"hqptuner/core/chain.py": ELSE_HOLDING_AN_IF})
    assert _run(root, _policy()) == [_deep("hqptuner/core/chain.py::f", 5)]


def test_nested_def_starts_its_own_count(repo: RepoFactory) -> None:
    """Port of test_a_nested_def_starts_its_own_count."""
    root = repo({"hqptuner/core/inner.py": NESTED_DEF_WITHIN_LIMIT})
    at_four = _run(root, _policy())
    at_two = _run(root, _policy(max_depth=2))
    assert (at_four, at_two) == (
        [],
        [
            _deep("hqptuner/core/inner.py::outer", 3, limit=2),
            _deep("hqptuner/core/inner.py::outer.inner", 3, limit=2),
        ],
    )


def test_nested_def_over_the_limit_is_named_by_dotted_name(repo: RepoFactory) -> None:
    """Port of test_a_nested_def_over_the_limit_is_reported_under_its_dotted_name."""
    root = repo({"hqptuner/core/inner.py": NESTED_DEF_OVER_LIMIT})
    assert _run(root, _policy()) == [_deep("hqptuner/core/inner.py::outer.inner", 5)]


def test_method_over_the_limit_is_named_by_dotted_name(repo: RepoFactory) -> None:
    """Port of test_a_method_over_the_limit_is_reported_under_its_dotted_name."""
    root = repo({"hqptuner/core/tuner.py": DEEP_METHOD})
    assert _run(root, _policy()) == [
        _deep("hqptuner/core/tuner.py::Tuner.set_volume", 5)
    ]


# --- depths(), as findings at a limit that exposes the depth -------------------


def test_deepest_nesting_a_function_reaches_is_measured(repo: RepoFactory) -> None:
    """Port of test_depths_reports_the_deepest_nesting_a_function_reaches."""
    root = repo({"hqptuner/core/deep.py": _function("if", 5)})
    findings = _run(root, _policy(max_depth=0))
    assert findings == [_deep("hqptuner/core/deep.py::f", 5, limit=0)]


def test_method_is_measured_under_its_dotted_name(repo: RepoFactory) -> None:
    """Port of test_depths_reports_a_method_under_its_dotted_name."""
    root = repo({"hqptuner/core/tuner.py": DEEP_METHOD})
    paths = [f.path for f in _run(root, _policy(max_depth=0))]
    assert "hqptuner/core/tuner.py::Tuner.set_volume" in paths


def test_nested_function_is_measured_under_its_dotted_name(repo: RepoFactory) -> None:
    """Port of test_depths_reports_a_nested_function_under_its_dotted_name."""
    root = repo({"hqptuner/core/inner.py": NESTED_DEF_OVER_LIMIT})
    paths = [f.path for f in _run(root, _policy(max_depth=0))]
    assert "hqptuner/core/inner.py::outer.inner" in paths


def test_enclosing_and_nested_function_are_both_measured(repo: RepoFactory) -> None:
    """Port of test_depths_reports_the_enclosing_function_before_the_one_nested_in_it."""  # noqa: E501
    root = repo({"hqptuner/core/inner.py": NESTED_DEF_OVER_LIMIT})
    paths = [f.path for f in _run(root, _policy(max_depth=0))]
    assert paths == [
        "hqptuner/core/inner.py::outer",
        "hqptuner/core/inner.py::outer.inner",
    ]


def test_nested_def_is_measured_apart_from_its_enclosing_function(
    repo: RepoFactory,
) -> None:
    """Port of test_depths_counts_a_nested_def_separately_from_its_enclosing_function."""  # noqa: E501
    root = repo({"hqptuner/core/inner.py": NESTED_DEF_WITHIN_LIMIT})
    assert _run(root, _policy(max_depth=2)) == [
        _deep("hqptuner/core/inner.py::outer", 3, limit=2),
        _deep("hqptuner/core/inner.py::outer.inner", 3, limit=2),
    ]


def test_module_with_no_functions_measures_nothing(repo: RepoFactory) -> None:
    """Port of test_depths_finds_nothing_in_a_module_with_no_functions."""
    # A limit below zero exposes every function, even one that nests nothing.
    root = repo(
        {"hqptuner/core/rates.py": "VALUE = 1\n", "hqptuner/core/flat.py": FLAT}
    )
    assert _run(root, _policy(max_depth=-1)) == [
        _deep("hqptuner/core/flat.py::f", 0, limit=-1)
    ]


# --- exempt --------------------------------------------------------------------


def test_exempt_function_passes(repo: RepoFactory) -> None:
    """Port of test_an_exempt_function_passes."""
    root = repo({"hqptuner/core/deep.py": _function("if", 5)})
    policy = _policy({"hqptuner/core/deep.py::f": WHY})
    plain = _run(root, _policy())
    assert (plain, _run(root, policy)) == (
        [_deep("hqptuner/core/deep.py::f", 5)],
        [],
    )


def test_exempt_function_is_not_named(repo: RepoFactory) -> None:
    """Port of test_an_exempt_function_is_not_named_on_stdout."""
    root = repo({"hqptuner/core/deep.py": _function("if", 5)})
    policy = _policy({"hqptuner/core/deep.py::f": WHY})
    plain = _named(_run(root, _policy()), "hqptuner/core/deep.py::f")
    exempt = _named(_run(root, policy), "hqptuner/core/deep.py::f")
    assert (plain, exempt) == (True, False)


def test_exemption_excuses_only_the_function_it_names(repo: RepoFactory) -> None:
    """Port of test_an_exemption_excuses_only_the_function_it_names."""
    source = _function("if", 5, name="f") + "\n" + _function("while", 5, name="g")
    root = repo({"hqptuner/core/deep.py": source})
    policy = _policy({"hqptuner/core/deep.py::f": WHY})
    assert _run(root, policy) == [_deep("hqptuner/core/deep.py::g", 5)]


def test_exemption_naming_a_dotted_method_excuses_it(repo: RepoFactory) -> None:
    """Port of test_an_exemption_naming_a_dotted_method_excuses_it."""
    root = repo({"hqptuner/core/tuner.py": DEEP_METHOD})
    key = "hqptuner/core/tuner.py::Tuner.set_volume"
    plain = _run(root, _policy())
    exempt = _run(root, _policy({key: "the wire frame nests this far"}))
    assert (plain, exempt) == ([_deep(key, 5)], [])


def test_exemption_whose_file_is_missing_fails(repo: RepoFactory) -> None:
    """Port of test_an_exemption_whose_file_is_not_on_disk_fails_as_stale."""
    root = repo({"hqptuner/core/flat.py": FLAT})
    key = "hqptuner/core/deleted.py::f"
    policy = _policy({key: "excused for a forgotten reason"})
    assert _run(root, policy) == [_stale(key, "names no file")]


def test_exemption_whose_file_is_missing_is_named(repo: RepoFactory) -> None:
    """Port of test_an_exemption_whose_file_is_not_on_disk_names_the_key_on_stdout."""  # noqa: E501
    root = repo({"hqptuner/core/flat.py": FLAT})
    key = "hqptuner/core/deleted.py::f"
    policy = _policy({key: "excused for a forgotten reason"})
    assert _named(_run(root, policy), key)


def test_exemption_whose_file_is_missing_is_one_finding(repo: RepoFactory) -> None:
    """Port of test_an_exemption_whose_file_is_not_on_disk_reports_on_one_line."""
    root = repo({"hqptuner/core/flat.py": FLAT})
    policy = _policy({"hqptuner/core/deleted.py::f": "excused for a forgotten reason"})
    assert len(_run(root, policy)) == 1


def test_exemption_on_function_now_within_the_limit_fails(repo: RepoFactory) -> None:
    """Port of test_an_exemption_naming_a_function_now_within_the_limit_fails_as_stale."""  # noqa: E501
    root = repo({"hqptuner/core/deep.py": _function("if", 4)})
    key = "hqptuner/core/deep.py::f"
    assert _run(root, _policy({key: WHY})) == [
        _stale(key, "nests 4 deep, within the limit of 4")
    ]


def test_exemption_on_function_now_within_the_limit_is_named(
    repo: RepoFactory,
) -> None:
    """Port of test_an_exemption_naming_a_function_now_within_the_limit_names_the_key_on_stdout."""  # noqa: E501
    root = repo({"hqptuner/core/deep.py": _function("if", 4)})
    key = "hqptuner/core/deep.py::f"
    assert _named(_run(root, _policy({key: WHY})), key)


def test_stale_exemption_is_one_finding(repo: RepoFactory) -> None:
    """Port of test_a_stale_exemption_reports_on_one_line."""
    root = repo({"hqptuner/core/deep.py": _function("if", 4)})
    assert len(_run(root, _policy({"hqptuner/core/deep.py::f": WHY}))) == 1


def test_stale_exemption_for_file_not_on_argv_fails(repo: RepoFactory) -> None:
    """Port of test_a_stale_exemption_for_a_file_not_passed_on_argv_still_fails."""
    root = repo(
        {
            "hqptuner/core/untouched.py": _function("if", 4),
            "hqptuner/core/committed.py": FLAT,
        }
    )
    key = "hqptuner/core/untouched.py::f"
    policy = _policy({key: "excused long ago"})
    assert _run(root, policy, ["hqptuner/core/committed.py"]) == [
        _stale(key, "nests 4 deep, within the limit of 4")
    ]


def test_live_exemption_for_file_not_on_argv_passes(repo: RepoFactory) -> None:
    """Port of test_a_live_exemption_for_a_file_not_passed_on_argv_passes."""
    root = repo(
        {
            "hqptuner/core/untouched.py": _function("if", 5),
            "hqptuner/core/committed.py": FLAT,
        }
    )
    policy = _policy({"hqptuner/core/untouched.py::f": WHY})
    committed = ["hqptuner/core/committed.py"]
    plain = _run(root, _policy(), committed)
    exempt = _run(root, policy, committed)
    assert (plain, exempt) == ([_deep("hqptuner/core/untouched.py::f", 5)], [])


# --- whole tree ----------------------------------------------------------------


def test_several_violations_all_fail(repo: RepoFactory) -> None:
    """Port of test_several_violations_all_fail_the_run."""
    root = repo({"hqptuner/core/deep.py": THREE_VIOLATIONS})
    assert _run(root, _policy()) != []


def test_several_violations_are_one_finding_each(repo: RepoFactory) -> None:
    """Port of test_several_violations_are_printed_one_line_each."""
    root = repo({"hqptuner/core/deep.py": THREE_VIOLATIONS})
    assert len(_run(root, _policy())) == 3


def test_several_violations_each_name_their_own_function(repo: RepoFactory) -> None:
    """Port of test_several_violations_each_name_their_own_function."""
    root = repo({"hqptuner/core/deep.py": THREE_VIOLATIONS})
    assert _run(root, _policy()) == [
        _deep("hqptuner/core/deep.py::one", 5),
        _deep("hqptuner/core/deep.py::three", 5),
        _deep("hqptuner/core/deep.py::two", 5),
    ]


def test_violation_in_a_later_file_fails(repo: RepoFactory) -> None:
    """Port of test_a_violation_in_a_later_file_fails_the_run."""
    root = repo(
        {
            "hqptuner/core/flat.py": FLAT,
            "hqptuner/core/chain.py": ELIF_CHAIN_THREE_DEEP,
            "hqptuner/core/deep.py": _function("if", 5),
        }
    )
    assert _run(root, _policy()) == [_deep("hqptuner/core/deep.py::f", 5)]


def test_tree_of_shallow_files_passes(repo: RepoFactory) -> None:
    """Port of test_a_tree_of_shallow_files_passes."""
    root = repo(
        {
            "hqptuner/core/flat.py": FLAT,
            "hqptuner/core/chain.py": ELIF_CHAIN_THREE_DEEP,
            "hqptuner/core/inner.py": NESTED_DEF_WITHIN_LIMIT,
            "hqptuner/core/limit.py": _function("if", 4),
        }
    )
    at_four = _run(root, _policy())
    at_three = _run(root, _policy(max_depth=3))
    assert (at_four, at_three) == (
        [],
        [_deep("hqptuner/core/limit.py::f", 4, limit=3)],
    )
