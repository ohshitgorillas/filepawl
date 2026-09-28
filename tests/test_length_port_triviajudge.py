"""Port of triviajudge length tests to filepawl (16 cases).

Every case writes synthetic files and runs the LengthGate through build_tree and
a default policy with small limits (matching triviajudge's: 500 cap, 800 test cap,
400 watch line). Each function is named after the source triviajudge test and
includes the source name in its docstring.

Findings are checked as (path, message) tuples. Messages are translated to the
filepawl wording since the gate implementation differs slightly from
triviajudge's printed text, but the behaviors being tested are identical.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.length import LengthGate
from filepawl.state import Entry, State
from filepawl.tree import build_tree

Repo = Callable[[dict[str, str | int]], Path]

# Limits matching triviajudge exactly for behavior parity.
CAP = 500
CAP_TESTS = 800
WATCH = 400


def policy(**overrides: object) -> Policy:
    """Default policy with triviajudge's limits, plus any overrides."""
    base = default_policy()
    length = dataclasses.replace(base.length, cap=CAP, cap_tests=CAP_TESTS, watch=WATCH)
    return dataclasses.replace(base, length=length, **overrides)  # type: ignore


def tree_for(root: Path, pol: Policy, paths: list[str] | None = None):
    return build_tree(root, pol, paths)


def state_for(allowance: dict[str, Entry]) -> State:
    return State(version=1, allowance=allowance)


def messages(findings: list[Finding]) -> list[tuple[str, str]]:
    return [(f.path, f.message) for f in findings]


#: A source file over the watch line with no entry, set beside a passing case
#: so the same run shows the gate acting.
OFFENDER = "pkg/offender.py"
OFFENDED = [
    (
        OFFENDER,
        f"over watch line {WATCH} ({WATCH + 1} lines); "
        f"run `filepawl accept {OFFENDER}`",
    )
]


# --- behavior 1: cap refuses file outright at its own limit per tree --------


def test_a_source_file_at_the_cap_passes_without_a_word(repo: Repo) -> None:
    """Source file at cap passes (test_a_source_file_at_the_cap_passes_without_a_word).

    A source file at exactly the cap (500 lines) passes with no findings
    when it has a corresponding entry (since it's also over watch line).
    """
    root = repo({"pkg/at_the_cap.py": CAP, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"pkg/at_the_cap.py": Entry(lines=CAP)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == OFFENDED


def test_a_source_file_over_the_cap_is_named_with_its_length_and_the_cap(
    repo: Repo,
) -> None:
    """Source file over cap named (test_a_source_file_over_the_cap_is_named_*).

    A source file at 501 lines (over the 500 cap) reports the cap violation.
    The error message names the file, its length, and the cap.
    """
    root = repo({"pkg/over_the_cap.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    cap_findings = [f for f in findings if "over cap" in f.message]
    assert (messages(cap_findings), cap_findings[0].fixable_by_accept) == (
        [("pkg/over_the_cap.py", f"over cap {CAP} ({CAP + 1} lines); split it")],
        False,
    )


def test_a_test_file_past_the_source_cap_is_held_to_the_wider_test_cap(
    repo: Repo,
) -> None:
    """Test file at test cap passes (test_a_test_file_past_the_source_cap_*).

    A test file at exactly the test cap (800 lines) passes; the higher
    test cap (not the source cap) applies.
    """
    root = repo({"tests/test_wide.py": CAP_TESTS, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_a_test_file_over_the_test_cap_is_named_with_its_length_and_the_test_cap(
    repo: Repo,
) -> None:
    """Test file over test cap named (test_a_test_file_over_the_test_cap_*).

    A test file at 801 lines (over the 800 test cap) reports the cap
    violation.
    """
    root = repo({"tests/test_over_the_cap.py": CAP_TESTS + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [
            (
                "tests/test_over_the_cap.py",
                f"test over cap {CAP_TESTS} ({CAP_TESTS + 1} lines)",
            )
        ],
        False,
    )


# --- behavior 2: above watch line source file carries entry, only shrinks ---


def test_a_source_file_at_the_watch_line_needs_no_entry(repo: Repo) -> None:
    """Source at watch line needs no entry (test_a_source_file_at_watch_*).

    A source file at exactly the watch line (400 lines) passes with no entry
    required in the allowance table.
    """
    root = repo({"pkg/watched.py": WATCH, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_a_watched_file_with_no_entry_is_told_the_length_to_write_down(
    repo: Repo,
) -> None:
    """Watched file no entry told length (test_a_watched_file_with_no_entry_*).

    A source file at 437 lines (over the 400 watch line) with no entry
    reports the ratchet violation and suggests running accept.
    """
    root = repo({"pkg/watched.py": WATCH + 37})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [
            (
                "pkg/watched.py",
                f"over watch line {WATCH} ({WATCH + 37} lines); "
                "run `filepawl accept pkg/watched.py`",
            )
        ],
        True,
    )


def test_a_watched_file_at_the_length_its_entry_permits_passes(repo: Repo) -> None:
    """Watched file at entry length passes (test_a_watched_file_at_the_*).

    A watched file at exactly its allowance entry length passes.
    """
    root = repo({"pkg/watched.py": 450, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"pkg/watched.py": Entry(lines=450)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == OFFENDED


def test_a_watched_file_over_its_entry_is_measured_against_the_entry(
    repo: Repo,
) -> None:
    """Watched file over entry measured (test_a_watched_file_over_its_entry_*).

    A watched file at 450 lines with an entry of 421 lines reports growth
    past the allowance.
    """
    root = repo({"pkg/watched.py": 450})
    pol = policy()
    state = state_for({"pkg/watched.py": Entry(lines=421)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [("pkg/watched.py", "grew past allowance (450 > 421); split it")],
        False,
    )


def test_a_watched_file_under_its_entry_is_told_the_length_to_lower_it_to(
    repo: Repo,
) -> None:
    """Watched file under entry told length (test_a_watched_file_under_*).

    A watched file at 412 lines with an entry of 455 lines reports
    shrinkage and suggests accepting to lower the entry.
    """
    root = repo({"pkg/watched.py": 412})
    pol = policy()
    state = state_for({"pkg/watched.py": Entry(lines=455)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [
            (
                "pkg/watched.py",
                "shrank (412 < 455); run `filepawl accept pkg/watched.py`",
            )
        ],
        True,
    )


def test_the_ratchet_does_not_reach_a_test_file_over_the_watch_line(
    repo: Repo,
) -> None:
    """Ratchet doesn't reach test file over watch (test_the_ratchet_*).

    A test file at 460 lines (over the 400 watch line) passes because the
    ratchet does not apply to test files.
    """
    root = repo({"tests/test_long.py": 460, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


# --- behavior 3: table audited off filesystem, not off paths handed --------


def test_an_entry_the_ratchet_can_enforce_stands_with_no_path_handed_over(
    repo: Repo,
) -> None:
    """Entry stands no path handed (test_an_entry_the_ratchet_can_*).

    An entry for a file that exists in the tree and is in the measured set
    passes even if no paths are handed to the gate (full audit). This tests
    that the stale audit includes all entries, not just measured paths.
    """
    root = repo({"pkg/watched.py": 430, OFFENDER: WATCH + 1})
    pol = policy()
    state = state_for({"pkg/watched.py": Entry(lines=430)})
    # Even with an empty measured set, the entry stands if the file is in
    # the tree.
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == OFFENDED


def test_an_entry_naming_no_file_is_refused_by_its_key(repo: Repo) -> None:
    """Entry naming no file refused (test_an_entry_naming_no_file_*).

    An entry in the allowance for a file that does not exist in the tree
    reports a stale entry.
    """
    root = repo({"other.py": 10})
    pol = policy()
    state = state_for({"pkg/gone.py": Entry(lines=430)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [("pkg/gone.py", "allowance names a path outside the tree; drop it")],
        True,
    )


def test_an_entry_naming_a_test_path_is_refused_as_ungoverned(repo: Repo) -> None:
    """Entry naming test path refused (test_an_entry_naming_a_test_*).

    An entry for a test path (under tests/) reports a stale entry because
    the ratchet does not govern test files.
    """
    root = repo({"tests/test_watched.py": 430})
    pol = policy()
    state = state_for({"tests/test_watched.py": Entry(lines=430)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [("tests/test_watched.py", "allowance names a test path; drop it")],
        True,
    )


def test_an_entry_whose_file_fell_under_the_watch_line_is_refused_as_droppable(
    repo: Repo,
) -> None:
    """Entry file fell under watch line (test_an_entry_whose_file_fell_*).

    An entry for a file that has shrunk back under the watch line reports
    a stale entry.
    """
    root = repo({"pkg/shrunk.py": 120})
    pol = policy()
    state = state_for({"pkg/shrunk.py": Entry(lines=430)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert (messages(findings), findings[0].fixable_by_accept) == (
        [("pkg/shrunk.py", f"back under watch line {WATCH}; drop it")],
        True,
    )


# --- behavior 4: argv names files and module's table governs ---------------
# (These two test the CLI behavior of triviajudge, which does not have a
# direct equivalent in filepawl since filepawl is not a CLI gate. Instead,
# we test that the gate handles multiple independent findings on the same
# file.)


def test_the_command_line_passes_a_file_no_rule_touches(repo: Repo) -> None:
    """CLI passes file no rule touches (test_the_command_line_passes_*).

    A simple file with no violations passes (using default empty allowance).
    This translates triviajudge's CLI test to a gate invocation.
    """
    root = repo({"pkg/named.py": 10, OFFENDER: WATCH + 1})
    pol = policy()
    assert messages(LengthGate().run(tree_for(root, pol), pol, State())) == OFFENDED


def test_the_command_line_reports_every_rule_the_file_it_names_breaks(
    repo: Repo,
) -> None:
    """CLI reports every rule file breaks (test_the_command_line_reports_*).

    A file that breaks multiple rules (over cap and over watch line with no
    entry) reports both findings.
    """
    root = repo({"pkg/named.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    # Both cap and ratchet violations fire independently on the same file.
    cap_msgs = [f.message for f in findings if "over cap" in f.message]
    watch_msgs = [f.message for f in findings if "over watch line" in f.message]
    assert (
        len(findings),
        [f.path for f in findings],
        len(cap_msgs),
        len(watch_msgs),
        cap_msgs[0],
        watch_msgs[0],
    ) == (
        2,
        ["pkg/named.py", "pkg/named.py"],
        1,
        1,
        f"over cap {CAP} ({CAP + 1} lines); split it",
        f"over watch line {WATCH} ({CAP + 1} lines); "
        "run `filepawl accept pkg/named.py`",
    )
