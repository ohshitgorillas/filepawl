"""Length gate: port of gauntlet test cases (19 cases).

Source: ~/dev/gauntlet/scripts/gates/file_length_selftest.py
This file exercises filepawl.gates.length.LengthGate through build_tree,
default_policy, and State, mirroring each gauntlet case's intent.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import Policy, default_policy
from filepawl.gates.base import Finding
from filepawl.gates.length import LengthGate
from filepawl.state import Entry, State
from filepawl.tree import Tree, build_tree

Repo = Callable[[dict[str, str | int]], Path]


# Small limits matching gauntlet's test scale; boundaries are what matter.
CAP = 50
CAP_TESTS = 80
WATCH = 40


def policy(**overrides: object) -> Policy:
    """Default policy with small limits, plus any overrides."""
    base = default_policy()
    length = dataclasses.replace(base.length, cap=CAP, cap_tests=CAP_TESTS, watch=WATCH)
    return dataclasses.replace(base, length=length, **overrides)  # type: ignore[arg-type]


def tree_for(root: Path, pol: Policy, paths: list[str] | None = None) -> Tree:
    return build_tree(root, pol, paths)


def state_for(allowance: dict[str, Entry]) -> State:
    return State(version=1, allowance=allowance)


def messages(findings: list[Finding]) -> list[tuple[str, str]]:
    return [(f.path, f.message) for f in findings]


# Test case 1: "a short source file with no entry passes"
def test_short_source_file_no_entry_passes(repo: Repo) -> None:
    """A file well under the watch line with no allowance entry passes."""
    root = repo({"hooks/small.py": 20})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert findings == []


# Test case 2: "a source file at the watch line passes with no entry"
def test_source_file_at_watch_line_passes(repo: Repo) -> None:
    """A file exactly at the watch line with no entry passes."""
    root = repo({"hooks/small.py": WATCH})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert findings == []


# Test case 3: "a source file over the watch line with no entry fails"
def test_source_file_over_watch_line_fails(repo: Repo) -> None:
    """A file over the watch line with no entry fails and names the file."""
    root = repo({"hooks/long.py": WATCH + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) == 1
    assert findings[0].path == "hooks/long.py"
    assert "hooks/long.py" in findings[0].message
    assert str(WATCH + 1) in findings[0].message


# Test case 4: "a source file matching its allowance exactly passes"
def test_file_matching_allowance_exactly_passes(repo: Repo) -> None:
    """A file at its exact allowance entry passes."""
    root = repo({"hooks/long.py": WATCH + 4})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=WATCH + 4)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert findings == []


# Test case 5: "a source file longer than its allowance fails"
def test_file_longer_than_allowance_fails(repo: Repo) -> None:
    """A file grown past its allowance fails and names the file."""
    root = repo({"hooks/long.py": WATCH + 5})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=WATCH + 4)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    grown = [f for f in findings if "grew past" in f.message]
    assert len(grown) > 0
    assert grown[0].path == "hooks/long.py"


# Test case 6: "a source file shorter than its allowance fails"
def test_file_shorter_than_allowance_fails(repo: Repo) -> None:
    """A file shrunk under its allowance fails and suggests the new value."""
    root = repo({"hooks/long.py": WATCH + 2})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=WATCH + 4)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    shrunk = [f for f in findings if "shrank" in f.message]
    assert len(shrunk) > 0
    assert str(WATCH + 2) in shrunk[0].message


# Test case 7: "an allowance naming no file on disk fails as stale"
def test_allowance_naming_no_file_fails(repo: Repo) -> None:
    """An allowance entry for a missing file fails as stale."""
    root = repo({"hooks/small.py": 20})
    pol = policy()
    state = state_for({"hooks/deleted.py": Entry(lines=WATCH + 4)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0
    assert findings[0].path == "hooks/deleted.py"


# Test case 8: "a live allowance for a file not on argv passes"
def test_live_allowance_for_unmeasured_file_passes(repo: Repo) -> None:
    """An allowance for a file not being measured passes when live."""
    root = repo({"hooks/untouched.py": 437, "hooks/small.py": 20})
    pol = policy()
    state = state_for({"hooks/untouched.py": Entry(lines=437)})
    # Measure only small.py
    findings = LengthGate().run(tree_for(root, pol, ["hooks/small.py"]), pol, state)
    assert findings == []


# Test case 9: "a stale allowance for a file not on argv still fails"
def test_stale_allowance_for_unmeasured_file_fails(repo: Repo) -> None:
    """An allowance for a file not being measured fails if the file is stale."""
    root = repo({"hooks/untouched.py": WATCH - 5, "hooks/small.py": 20})
    pol = policy()
    state = state_for({"hooks/untouched.py": Entry(lines=WATCH + 4)})
    # Measure only small.py, but the full state table is still audited
    # untouched.py is stale because it's back under watch line
    findings = LengthGate().run(tree_for(root, pol, ["hooks/small.py"]), pol, state)
    assert len(findings) > 0
    assert findings[0].path == "hooks/untouched.py"


# Test case 10: "an allowance for a file back under the watch line fails as stale"
def test_allowance_for_file_back_under_watch_line_fails(repo: Repo) -> None:
    """An allowance for a file that shrank back under the watch line fails."""
    root = repo({"hooks/long.py": WATCH})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=WATCH + 4)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0
    assert findings[0].path == "hooks/long.py"


# Test case 11: "an allowance for a file at the watch line fails as stale"
def test_allowance_for_file_at_watch_line_fails(repo: Repo) -> None:
    """An allowance for a file at exactly the watch line fails as stale."""
    root = repo({"hooks/long.py": WATCH})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=WATCH)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0


# Test case 12: "a source file at the hard cap passes with a matching allowance"
def test_file_at_hard_cap_passes(repo: Repo) -> None:
    """A file at the hard cap with a matching entry passes."""
    root = repo({"hooks/long.py": CAP})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=CAP)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert findings == []


# Test case 13: "an allowance cannot sell permission past the hard cap"
def test_allowance_cannot_exceed_hard_cap(repo: Repo) -> None:
    """An entry cannot permit a file longer than the hard cap."""
    root = repo({"hooks/long.py": CAP + 1})
    pol = policy()
    state = state_for({"hooks/long.py": Entry(lines=CAP + 1)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0


# Test case 14: "a source file over the hard cap with no entry fails"
def test_file_over_hard_cap_no_entry_fails(repo: Repo) -> None:
    """A file over the hard cap with no entry fails."""
    root = repo({"hooks/long.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0


# Test case 15: "a test file over the watch line passes with no entry"
def test_test_file_over_watch_line_passes(repo: Repo) -> None:
    """A test file over the watch line but under its cap passes (no ratchet)."""
    root = repo({"tests/test_many.py": CAP_TESTS - 10})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert findings == []


# Test case 16: "a test file at the 800-line cap passes"
def test_test_file_at_tests_cap_passes(repo: Repo) -> None:
    """A test file at the test cap passes."""
    root = repo({"tests/test_many.py": CAP_TESTS})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert findings == []


# Test case 17: "a test file over the 800-line cap fails"
def test_test_file_over_tests_cap_fails(repo: Repo) -> None:
    """A test file over the test cap fails."""
    root = repo({"tests/test_many.py": CAP_TESTS + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert len(findings) > 0


# Test case 18: "an allowance naming a test path fails as stale"
def test_allowance_naming_test_path_fails(repo: Repo) -> None:
    """An allowance entry for a test path fails as stale (no ratchet for tests)."""
    root = repo({"tests/test_many.py": CAP_TESTS - 10})
    pol = policy()
    state = state_for({"tests/test_many.py": Entry(lines=CAP_TESTS - 10)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert len(findings) > 0


# Test case 19: "one offender among compliant files fails the gate"
def test_one_offender_among_compliant_files(repo: Repo) -> None:
    """When one file violates the gate, only that offender is reported."""
    files: dict[str, str | int] = {
        "hooks/one.py": 20,
        "hooks/two.py": WATCH + 15,
        "hooks/three.py": WATCH + 30,
        "hooks/four.py": 10,
    }
    root = repo(files)
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    # hooks/two.py and hooks/three.py should be reported (over watch line)
    # hooks/one.py and hooks/four.py should not be reported
    reported_paths = [f.path for f in findings]
    assert "hooks/two.py" in reported_paths
    assert "hooks/three.py" in reported_paths
    assert "hooks/one.py" not in reported_paths
    assert "hooks/four.py" not in reported_paths
