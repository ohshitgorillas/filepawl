"""Port of ~/dev/hqptuner/tests/gates/test_file_length_ratchet.py (33 cases).

These tests exercise filepawl.gates.length.LengthGate through filepawl.tree.build_tree,
filepawl.config.default_policy(), and filepawl.state.State/Entry, using the repo fixture
from tests/conftest.py exactly as tests/test_length_gate.py does.

Source test names are in each function's docstring. Cases testing subprocess invocation
(test_running_the_script_*) and fallback to shipped ALLOWANCE mapping are omitted
because filepawl's state and config model differ from hqptuner's.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.length import LengthGate
from filepawl.state import Entry, State
from filepawl.tree import Tree, build_tree

Repo = Callable[[dict[str, str | int]], Path]

# Use same limits as test_length_gate.py for consistency
CAP = 50
CAP_TESTS = 80
WATCH = 40


def policy(**overrides: object) -> Policy:
    """Default policy with the small limits above, plus any overrides."""
    base = default_policy()
    length = dataclasses.replace(base.length, cap=CAP, cap_tests=CAP_TESTS, watch=WATCH)
    return dataclasses.replace(base, length=length, **overrides)  # type: ignore[arg-type]


def tree_for(root: Path, pol: Policy, paths: list[str] | None = None) -> Tree:
    return build_tree(root, pol, paths)


def state_for(allowance: dict[str, Entry]) -> State:
    return State(version=1, allowance=allowance)


def messages(findings: list[Finding]) -> list[tuple[str, str]]:
    return [(f.path, f.message) for f in findings]


#: A source file over the watch line with no entry, set beside a passing case
#: so the same run shows the gate acting.
OFFENDER = "hqptuner/offender.py"
OFFENDED = [
    (
        OFFENDER,
        f"over watch line {WATCH} ({WATCH + 1} lines); "
        f"run `filepawl accept {OFFENDER}`",
    )
]


def named(findings: list[Finding], path: str) -> bool:
    return any(f.path == path for f in findings)


# --- cap and ratchet basics -------------------------------------------------------


def test_a_short_source_file_with_no_allowance_entry_passes(repo: Repo) -> None:
    """test_a_short_source_file_with_no_allowance_entry_passes"""
    root = repo({"hqptuner/small.py": 12, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_a_source_file_exactly_at_the_watch_line_passes_with_no_allowance_entry(
    repo: Repo,
) -> None:
    """test_a_source_file_exactly_at_the_watch_line_passes_with_no_allowance_entry

    The watch line is a threshold to exceed, not to reach: WATCH is still quiet.
    """
    root = repo({"hqptuner/borderline.py": WATCH, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_a_source_file_over_the_watch_line_with_no_allowance_entry_fails(
    repo: Repo,
) -> None:
    """test_a_source_file_over_the_watch_line_with_no_allowance_entry_fails"""
    root = repo({"hqptuner/creeping.py": WATCH + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0
    assert any("over watch line" in f.message for f in findings)


def test_a_source_file_over_the_watch_line_with_no_allowance_entry_is_named_on_stdout(
    repo: Repo,
) -> None:
    """test_a_source_file_over_the_watch_line_with_no_allowance_entry_is_named_on_stdout"""
    root = repo({"hqptuner/creeping.py": WATCH + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert any(f.path == "hqptuner/creeping.py" for f in findings)


def test_a_source_file_matching_its_allowance_exactly_passes(repo: Repo) -> None:
    """test_a_source_file_matching_its_allowance_exactly_passes"""
    root = repo({"hqptuner/known_long.py": WATCH + 5, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"hqptuner/known_long.py": Entry(lines=WATCH + 5)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == OFFENDED


def test_a_source_file_matching_its_allowance_exactly_is_not_named_on_stdout(
    repo: Repo,
) -> None:
    """test_a_source_file_matching_its_allowance_exactly_is_not_named_on_stdout

    An allowance is silent — it permits the length rather than warning about it.
    """
    root = repo({"hqptuner/known_long.py": WATCH + 5, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"hqptuner/known_long.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    shown = (named(findings, OFFENDER), named(findings, "hqptuner/known_long.py"))
    assert shown == (True, False)


def test_a_source_file_longer_than_its_allowance_fails(repo: Repo) -> None:
    """test_a_source_file_longer_than_its_allowance_fails"""
    root = repo({"hqptuner/grown.py": WATCH + 10})
    pol = policy()
    state = state_for({"hqptuner/grown.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert any(f.path == "hqptuner/grown.py" for f in findings)


def test_a_source_file_longer_than_its_allowance_is_named_on_stdout(
    repo: Repo,
) -> None:
    """test_a_source_file_longer_than_its_allowance_is_named_on_stdout"""
    root = repo({"hqptuner/grown.py": WATCH + 10})
    pol = policy()
    state = state_for({"hqptuner/grown.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    msg = messages(findings)
    assert any(path == "hqptuner/grown.py" for path, _ in msg)


def test_a_source_file_shorter_than_its_allowance_fails(repo: Repo) -> None:
    """test_a_source_file_shorter_than_its_allowance_fails

    The ratchet only turns one way: an allowance the file has outgrown downwards is
    owed a rewrite.
    """
    root = repo({"hqptuner/shrunk.py": WATCH + 1})
    pol = policy()
    state = state_for({"hqptuner/shrunk.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0


def test_a_source_file_shorter_than_its_allowance_is_told_the_lower_number(
    repo: Repo,
) -> None:
    """test_a_source_file_shorter_than_its_allowance_is_told_the_lower_number"""
    root = repo({"hqptuner/shrunk.py": WATCH + 1})
    pol = policy()
    state = state_for({"hqptuner/shrunk.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    msg = messages(findings)
    assert any(
        "hqptuner/shrunk.py" in path and "shrank" in message for path, message in msg
    )


def test_an_allowance_whose_path_is_not_on_disk_fails_as_stale(repo: Repo) -> None:
    """test_an_allowance_whose_path_is_not_on_disk_fails_as_stale"""
    root = repo({"hqptuner/present.py": 10})
    pol = policy()
    state = state_for({"hqptuner/deleted_last_year.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert any(f.path == "hqptuner/deleted_last_year.py" for f in findings)


def test_an_allowance_whose_path_is_not_on_disk_is_named_on_stdout(
    repo: Repo,
) -> None:
    """test_an_allowance_whose_path_is_not_on_disk_is_named_on_stdout"""
    root = repo({"hqptuner/present.py": 10})
    pol = policy()
    state = state_for({"hqptuner/deleted_last_year.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    msg = messages(findings)
    assert any("hqptuner/deleted_last_year.py" in path for path, _ in msg)


def test_a_stale_allowance_for_a_file_not_passed_on_argv_still_fails(
    repo: Repo,
) -> None:
    """test_a_stale_allowance_for_a_file_not_passed_on_argv_still_fails

    Staleness is judged against the filesystem, so which subset was handed over does
    not hide it.
    """
    root = repo({"hqptuner/untouched.py": 10, "hqptuner/committed.py": 10})
    pol = policy()
    state = state_for({"hqptuner/untouched.py": Entry(lines=WATCH + 5)})
    # Only measure committed.py but state has entry for untouched.py
    tree = tree_for(root, pol, ["hqptuner/committed.py"])
    findings = LengthGate().run(tree, pol, state)
    # The stale entry for untouched.py should be flagged
    assert any(f.path == "hqptuner/untouched.py" for f in findings)


def test_a_live_allowance_for_a_file_not_passed_on_argv_passes(
    repo: Repo,
) -> None:
    """test_a_live_allowance_for_a_file_not_passed_on_argv_passes

    A partial commit reads the untouched file from disk and finds its entry still true.
    """
    root = repo(
        {
            "hqptuner/untouched.py": WATCH + 5,
            "hqptuner/committed.py": 10,
            OFFENDER: WATCH + 1,
        }
    )
    pol = policy()
    state = state_for({"hqptuner/untouched.py": Entry(lines=WATCH + 5)})
    # Only measure the committed files but state has entry for untouched.py
    tree = tree_for(root, pol, ["hqptuner/committed.py", OFFENDER])
    findings = LengthGate().run(tree, pol, state)
    # No finding for untouched.py since it matches its entry
    assert (named(findings, OFFENDER), named(findings, "hqptuner/untouched.py")) == (
        True,
        False,
    )


def test_an_allowance_for_a_file_back_under_the_watch_line_fails_as_stale(
    repo: Repo,
) -> None:
    """test_an_allowance_for_a_file_back_under_the_watch_line_fails_as_stale

    Once a file is quiet again its entry is dead weight, not a lower number to write
    down.
    """
    root = repo({"hqptuner/reformed.py": WATCH - 5})
    pol = policy()
    state = state_for({"hqptuner/reformed.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert any(f.path == "hqptuner/reformed.py" for f in findings)


def test_an_allowance_for_a_file_exactly_at_the_watch_line_fails_as_stale(
    repo: Repo,
) -> None:
    """test_an_allowance_for_a_file_exactly_at_the_watch_line_fails_as_stale

    At the watch line the ratchet has nothing left to hold, so the entry has to go.
    """
    root = repo({"hqptuner/reformed.py": WATCH})
    pol = policy()
    state = state_for({"hqptuner/reformed.py": Entry(lines=WATCH)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert any(f.path == "hqptuner/reformed.py" for f in findings)


def test_an_allowance_for_a_file_back_under_the_watch_line_is_named_on_stdout(
    repo: Repo,
) -> None:
    """test_an_allowance_for_a_file_back_under_the_watch_line_is_named_on_stdout"""
    root = repo({"hqptuner/reformed.py": WATCH - 5})
    pol = policy()
    state = state_for({"hqptuner/reformed.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    msg = messages(findings)
    assert any("hqptuner/reformed.py" in path for path, _ in msg)


def test_a_source_file_over_the_hard_cap_fails_even_with_an_allowance_permitting_it(
    repo: Repo,
) -> None:
    """test_a_source_file_over_the_hard_cap_fails_even_with_an_allowance_permitting_it

    The allowance table buys time under the cap; it cannot sell permission past it.
    """
    root = repo({"hqptuner/enormous.py": CAP + 1})
    pol = policy()
    state = state_for({"hqptuner/enormous.py": Entry(lines=CAP + 1)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0
    assert any("over cap" in f.message for f in findings)


def test_a_source_file_over_the_hard_cap_fails_with_no_allowance_entry(
    repo: Repo,
) -> None:
    """test_a_source_file_over_the_hard_cap_fails_with_no_allowance_entry"""
    root = repo({"hqptuner/enormous.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0


def test_one_offending_file_among_compliant_ones_fails_the_gate(
    repo: Repo,
) -> None:
    """test_one_offending_file_among_compliant_ones_fails_the_gate

    The question is asked of every path given, not only the first.
    """
    root = repo(
        {
            "hqptuner/one.py": 9,
            "hqptuner/two.py": 12,
            "hqptuner/creeping.py": WATCH + 6,
            "hqptuner/three.py": 4,
        }
    )
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0


# --- test files and caps -------------------------------------------------------


def test_a_test_file_over_the_watch_line_passes_with_no_allowance_entry(
    repo: Repo,
) -> None:
    """test_a_test_file_over_the_watch_line_passes_with_no_allowance_entry

    Suites sit outside the ratchet: a flat list of cases has no missing abstraction
    to surface.
    """
    root = repo({"tests/test_many_cases.py": WATCH + 10, OFFENDER: WATCH + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == OFFENDED


def test_a_test_file_under_the_eight_hundred_line_cap_passes(
    repo: Repo,
) -> None:
    """test_a_test_file_under_the_eight_hundred_line_cap_passes"""
    root = repo({"tests/test_many_cases.py": CAP_TESTS - 1, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_a_test_file_over_the_eight_hundred_line_cap_fails(
    repo: Repo,
) -> None:
    """test_a_test_file_over_the_eight_hundred_line_cap_fails"""
    root = repo({"tests/test_sprawling.py": CAP_TESTS + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0


def test_an_allowance_naming_a_test_file_fails_as_stale(
    repo: Repo,
) -> None:
    """test_an_allowance_naming_a_test_file_fails_as_stale

    The table must not carry entries the ratchet will never enforce.
    """
    root = repo({"tests/test_many_cases.py": WATCH + 10})
    pol = policy()
    state = state_for({"tests/test_many_cases.py": Entry(lines=WATCH + 10)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert any(f.path == "tests/test_many_cases.py" for f in findings)


def test_an_allowance_naming_a_test_file_is_named_on_stdout(
    repo: Repo,
) -> None:
    """test_an_allowance_naming_a_test_file_is_named_on_stdout"""
    root = repo({"tests/test_many_cases.py": WATCH + 10})
    pol = policy()
    state = state_for({"tests/test_many_cases.py": Entry(lines=WATCH + 10)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    msg = messages(findings)
    assert any("tests/test_many_cases.py" in path for path, _ in msg)


@pytest.mark.parametrize("expected", ["hqptuner/first.py", "hqptuner/second.py"])
def test_every_offending_file_is_reported_not_only_the_first(
    repo: Repo, expected: str
) -> None:
    """test_every_offending_file_is_reported_not_only_the_first"""
    root = repo(
        {
            "hqptuner/first.py": WATCH + 5,
            "hqptuner/second.py": WATCH + 10,
            "hqptuner/fine.py": 3,
        }
    )
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert any(f.path == expected for f in findings)


def test_a_compliant_file_beside_an_offender_is_not_named_on_stdout(
    repo: Repo,
) -> None:
    """test_a_compliant_file_beside_an_offender_is_not_named_on_stdout"""
    root = repo(
        {
            "hqptuner/creeping.py": WATCH + 5,
            "hqptuner/fine.py": 3,
        }
    )
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    shown = (
        named(findings, "hqptuner/creeping.py"),
        named(findings, "hqptuner/fine.py"),
    )
    assert shown == (True, False)


def test_a_source_file_exactly_at_the_hard_cap_passes_with_a_matching_allowance(
    repo: Repo,
) -> None:
    """test_a_source_file_exactly_at_the_hard_cap_passes_with_a_matching_allowance

    CAP is the cap, not the first line past it: an allowance still buys the file its
    length.
    """
    root = repo({"hqptuner/at_the_cap.py": CAP, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"hqptuner/at_the_cap.py": Entry(lines=CAP)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == OFFENDED


def test_a_test_file_exactly_at_the_eight_hundred_line_cap_passes(
    repo: Repo,
) -> None:
    """test_a_test_file_exactly_at_the_eight_hundred_line_cap_passes

    CAP_TESTS is the cap suites are held to, and reaching it is not exceeding it.
    """
    root = repo({"tests/test_many_cases.py": CAP_TESTS, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED
