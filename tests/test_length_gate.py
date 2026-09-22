"""Length gate: cap, ratchet, stale audit and `accept` (docs/design.md §6.1, §7)."""

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

# Small limits keep the synthetic trees short; the boundaries are what matter.
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


def test_gate_name_is_length() -> None:
    assert LengthGate().name == "length"


# --- cap ---------------------------------------------------------------


def test_file_at_cap_passes(repo: Repo) -> None:
    root = repo({"a.py": CAP})
    pol = policy()
    state = state_for({"a.py": Entry(lines=CAP)})
    assert LengthGate().run(tree_for(root, pol), pol, state) == []


def test_file_over_cap_fails_and_accept_cannot_fix_it(repo: Repo) -> None:
    root = repo({"a.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    cap_findings = [f for f in findings if "over cap" in f.message]
    assert messages(cap_findings) == [
        ("a.py", f"over cap {CAP} ({CAP + 1} lines); split it")
    ]
    assert cap_findings[0].fixable_by_accept is False


def test_over_cap_file_also_reports_the_missing_entry(repo: Repo) -> None:
    """Both rules are read off the same number and fire independently.

    Shared by all three source scripts, which append `cap_fault` and
    `ratchet_fault` for the same file without short-circuiting.
    """
    root = repo({"a.py": CAP + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == [
        ("a.py", f"over cap {CAP} ({CAP + 1} lines); split it"),
        (
            "a.py",
            f"over watch line {WATCH} ({CAP + 1} lines); " "run `filepawl accept a.py`",
        ),
    ]


def test_test_file_at_tests_cap_passes(repo: Repo) -> None:
    root = repo({"tests/test_a.py": CAP_TESTS})
    pol = policy()
    assert LengthGate().run(tree_for(root, pol), pol, State()) == []


def test_test_file_over_tests_cap_fails(repo: Repo) -> None:
    root = repo({"tests/test_a.py": CAP_TESTS + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == [
        ("tests/test_a.py", f"test over cap {CAP_TESTS} ({CAP_TESTS + 1} lines)")
    ]
    assert findings[0].fixable_by_accept is False


def test_test_file_over_watch_needs_no_entry(repo: Repo) -> None:
    root = repo({"tests/test_a.py": WATCH + 5})
    pol = policy()
    assert LengthGate().run(tree_for(root, pol), pol, State()) == []


# --- exempt ------------------------------------------------------------


def test_exempt_file_skips_only_the_cap_check(repo: Repo) -> None:
    root = repo({"big.py": CAP + 10})
    pol = policy(exempt={"big.py": "kept whole"})
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == [
        (
            "big.py",
            f"over watch line {WATCH} ({CAP + 10} lines); "
            "run `filepawl accept big.py`",
        )
    ]


def test_exempt_file_at_its_entry_passes(repo: Repo) -> None:
    root = repo({"big.py": CAP + 10})
    pol = policy(exempt={"big.py": "kept whole"})
    state = state_for({"big.py": Entry(lines=CAP + 10)})
    assert LengthGate().run(tree_for(root, pol), pol, state) == []


def test_exempt_file_may_not_grow(repo: Repo) -> None:
    root = repo({"big.py": CAP + 10})
    pol = policy(exempt={"big.py": "kept whole"})
    state = state_for({"big.py": Entry(lines=CAP + 9)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == [
        ("big.py", f"grew past allowance ({CAP + 10} > {CAP + 9}); split it")
    ]


def test_exempt_naming_a_path_outside_the_tree_is_reported(repo: Repo) -> None:
    root = repo({"a.py": 5})
    pol = policy(exempt={"gone.py": "stale reason"})
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == [("gone.py", "exempt names a path outside the tree")]
    assert findings[0].fixable_by_accept is False


# --- ratchet -----------------------------------------------------------


def test_file_at_watch_line_needs_no_entry(repo: Repo) -> None:
    root = repo({"a.py": WATCH})
    pol = policy()
    assert LengthGate().run(tree_for(root, pol), pol, State()) == []


def test_file_over_watch_without_entry_names_the_accept_command(repo: Repo) -> None:
    root = repo({"pkg/a.py": WATCH + 1})
    pol = policy()
    findings = LengthGate().run(tree_for(root, pol), pol, State())
    assert messages(findings) == [
        (
            "pkg/a.py",
            f"over watch line {WATCH} ({WATCH + 1} lines); "
            "run `filepawl accept pkg/a.py`",
        )
    ]
    assert findings[0].fixable_by_accept is True


def test_file_equal_to_entry_passes(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 5})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 5)})
    assert LengthGate().run(tree_for(root, pol), pol, state) == []


def test_grown_file_fails_and_accept_cannot_fix_it(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 6})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert messages(findings) == [
        ("a.py", f"grew past allowance ({WATCH + 6} > {WATCH + 5}); split it")
    ]
    assert findings[0].fixable_by_accept is False


def test_shrunk_file_fails_and_names_the_accept_command(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 4})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert messages(findings) == [
        ("a.py", f"shrank ({WATCH + 4} < {WATCH + 5}); run `filepawl accept a.py`")
    ]
    assert findings[0].fixable_by_accept is True


def test_multiple_offenders_are_reported_together_sorted_by_path(repo: Repo) -> None:
    root = repo({"b.py": WATCH + 1, "a.py": WATCH + 2, "c.py": CAP + 1})
    pol = policy()
    state = state_for({"c.py": Entry(lines=CAP + 1)})
    paths = [f.path for f in LengthGate().run(tree_for(root, pol), pol, state)]
    assert paths == ["a.py", "b.py", "c.py"]


# --- stale audit -------------------------------------------------------


def test_stale_entry_outside_the_tree(repo: Repo) -> None:
    root = repo({"a.py": 5})
    pol = policy()
    state = state_for({"gone.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert messages(findings) == [
        ("gone.py", "allowance names a path outside the tree; drop it")
    ]
    assert findings[0].fixable_by_accept is True


def test_untracked_file_on_disk_is_outside_the_tree(repo: Repo) -> None:
    root = repo({"a.py": 5})
    (root / "untracked.py").write_text("x\n" * (WATCH + 5), encoding="utf-8")
    pol = policy()
    state = state_for({"untracked.py": Entry(lines=WATCH + 5)})
    assert messages(LengthGate().run(tree_for(root, pol), pol, state)) == [
        ("untracked.py", "allowance names a path outside the tree; drop it")
    ]


def test_tracked_file_deleted_from_disk_is_outside_the_tree(repo: Repo) -> None:
    root = repo({"a.py": 5, "gone.py": WATCH + 5})
    (root / "gone.py").unlink()
    pol = policy()
    state = state_for({"gone.py": Entry(lines=WATCH + 5)})
    tree = tree_for(root, pol)
    assert messages(LengthGate().run(tree, pol, state)) == [
        ("gone.py", "allowance names a path outside the tree; drop it")
    ]
    assert LengthGate().accept(tree, pol, state).allowance == {}


def test_stale_entry_naming_a_test_path(repo: Repo) -> None:
    root = repo({"tests/test_a.py": WATCH + 5})
    pol = policy()
    state = state_for({"tests/test_a.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert messages(findings) == [
        ("tests/test_a.py", "allowance names a test path; drop it")
    ]
    assert findings[0].fixable_by_accept is True


def test_stale_entry_back_under_the_watch_line(repo: Repo) -> None:
    root = repo({"a.py": WATCH})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 5)})
    findings = LengthGate().run(tree_for(root, pol), pol, state)
    assert messages(findings) == [("a.py", f"back under watch line {WATCH}; drop it")]
    assert findings[0].fixable_by_accept is True


def test_stale_audit_covers_the_whole_table_when_measured_is_narrowed(
    repo: Repo,
) -> None:
    root = repo(
        {
            "picked.py": WATCH + 3,
            "shrunk.py": WATCH,
            "tests/test_a.py": 5,
        }
    )
    pol = policy()
    state = state_for(
        {
            "gone.py": Entry(lines=WATCH + 5),
            "shrunk.py": Entry(lines=WATCH + 5),
            "tests/test_a.py": Entry(lines=WATCH + 5),
        }
    )
    tree = tree_for(root, pol, ["picked.py"])
    assert tree.measured() == ("picked.py",)
    assert messages(LengthGate().run(tree, pol, state)) == [
        (
            "picked.py",
            f"over watch line {WATCH} ({WATCH + 3} lines); "
            "run `filepawl accept picked.py`",
        ),
        ("gone.py", "allowance names a path outside the tree; drop it"),
        ("shrunk.py", f"back under watch line {WATCH}; drop it"),
        ("tests/test_a.py", "allowance names a test path; drop it"),
    ]


def test_narrowing_hides_only_the_unmeasured_files(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    pol = policy()
    tree = tree_for(root, pol, ["b.py"])
    assert [f.path for f in LengthGate().run(tree, pol, State())] == ["b.py"]


# --- accept ------------------------------------------------------------


def test_accept_adds_a_missing_entry_at_current_length(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 7})
    pol = policy()
    state = LengthGate().accept(tree_for(root, pol), pol, State())
    assert state.allowance == {"a.py": Entry(lines=WATCH + 7)}


def test_accept_lowers_an_entry_whose_file_shrank(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 2})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 9)})
    assert LengthGate().accept(tree_for(root, pol), pol, state).allowance == {
        "a.py": Entry(lines=WATCH + 2)
    }


def test_accept_preserves_reason_when_it_lowers(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 2})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 9, reason="record and readers")})
    assert LengthGate().accept(tree_for(root, pol), pol, state).allowance == {
        "a.py": Entry(lines=WATCH + 2, reason="record and readers")
    }


def test_accept_refuses_to_raise_and_the_finding_survives(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 9})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 2)})
    tree = tree_for(root, pol)
    after = LengthGate().accept(tree, pol, state)
    assert after.allowance == {"a.py": Entry(lines=WATCH + 2)}
    assert messages(LengthGate().run(tree, pol, after)) == [
        ("a.py", f"grew past allowance ({WATCH + 9} > {WATCH + 2}); split it")
    ]


def test_accept_does_not_raise_on_a_grown_file(repo: Repo) -> None:
    root = repo({"a.py": CAP + 5})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 1)})
    LengthGate().accept(tree_for(root, pol), pol, state)


def test_accept_drops_every_stale_kind(repo: Repo) -> None:
    root = repo(
        {
            "keep.py": WATCH + 3,
            "shrunk.py": WATCH,
            "tests/test_a.py": 5,
        }
    )
    pol = policy()
    state = state_for(
        {
            "gone.py": Entry(lines=WATCH + 5),
            "keep.py": Entry(lines=WATCH + 3),
            "shrunk.py": Entry(lines=WATCH + 5),
            "tests/test_a.py": Entry(lines=WATCH + 5),
        }
    )
    assert LengthGate().accept(tree_for(root, pol), pol, state).allowance == {
        "keep.py": Entry(lines=WATCH + 3)
    }


def test_accept_drops_stale_entries_outside_the_measured_set(repo: Repo) -> None:
    root = repo({"picked.py": WATCH + 3, "shrunk.py": WATCH})
    pol = policy()
    state = state_for(
        {"gone.py": Entry(lines=WATCH + 5), "shrunk.py": Entry(lines=WATCH + 5)}
    )
    after = LengthGate().accept(tree_for(root, pol, ["picked.py"]), pol, state)
    assert after.allowance == {"picked.py": Entry(lines=WATCH + 3)}


def test_accept_adds_only_within_the_measured_set(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 1, "b.py": WATCH + 1})
    pol = policy()
    after = LengthGate().accept(tree_for(root, pol, ["b.py"]), pol, State())
    assert after.allowance == {"b.py": Entry(lines=WATCH + 1)}


def test_accept_leaves_unwatched_and_test_files_out_of_the_table(repo: Repo) -> None:
    root = repo({"a.py": WATCH, "tests/test_a.py": WATCH + 9})
    pol = policy()
    assert LengthGate().accept(tree_for(root, pol), pol, State()).allowance == {}


def test_accept_adds_an_exempt_file_over_cap(repo: Repo) -> None:
    root = repo({"big.py": CAP + 10})
    pol = policy(exempt={"big.py": "kept whole"})
    assert LengthGate().accept(tree_for(root, pol), pol, State()).allowance == {
        "big.py": Entry(lines=CAP + 10)
    }


def test_accept_leaves_a_clean_state_untouched(repo: Repo) -> None:
    root = repo({"a.py": WATCH + 3})
    pol = policy()
    state = state_for({"a.py": Entry(lines=WATCH + 3, reason="why")})
    after = LengthGate().accept(tree_for(root, pol), pol, state)
    assert after.allowance == state.allowance
    assert after.version == state.version


def test_accept_clears_every_fixable_finding(repo: Repo) -> None:
    root = repo(
        {
            "add.py": WATCH + 6,
            "shrunk.py": WATCH + 2,
            "under.py": WATCH,
            "tests/test_a.py": 5,
        }
    )
    pol = policy()
    state = state_for(
        {
            "gone.py": Entry(lines=WATCH + 5),
            "shrunk.py": Entry(lines=WATCH + 5),
            "under.py": Entry(lines=WATCH + 5),
            "tests/test_a.py": Entry(lines=WATCH + 5),
        }
    )
    tree = tree_for(root, pol)
    gate = LengthGate()
    assert [f for f in gate.run(tree, pol, state) if f.fixable_by_accept]
    after = gate.accept(tree, pol, state)
    assert [f for f in gate.run(tree, pol, after) if f.fixable_by_accept] == []
