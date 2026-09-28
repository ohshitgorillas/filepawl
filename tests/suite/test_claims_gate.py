"""Tests for filepawl.gates.suite.claims: the claims gate (design.md §6.22)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SuiteGatePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.claims import ClaimsGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

MESSAGE = (
    "makes more than one claim — one claim per test; split it, or pack one"
    " contrast into a tuple assertion"
)

PATH = "tests/test_m.py"

#: A test that fails the gate, set beside a passing case so the same run
#: shows the gate acting.
TWO_CLAIMS = "def test_bad():\n    assert run() == 1\n    assert run() == 2\n"
BAD = Finding(f"{PATH}::test_bad", MESSAGE)

#: Each guard form, with the subject it narrows.
GUARDS = [
    ("out is not None", "out"),
    ("None is not out", "out"),
    ("isinstance(out, Result)", "out"),
    ("out.body is not None", "out.body"),
    ("isinstance(out[0], Result)", "out[0]"),
]


def _test(*lines: str, name: str = "test_f") -> str:
    return f"def {name}():\n" + "".join(f"    {line}\n" for line in lines)


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.claims.exempt] {key!r}: {message}"
    )


def _policy(**claims: object) -> Policy:
    table = SuiteGatePolicy(**claims)  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=SuitePolicies(claims=table))


def _run(root: Path, policy: Policy) -> list[Finding]:
    return ClaimsGate().run(build_tree(root, policy), policy, State())


def _judge(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines` beside a test that fails."""
    root = repo({PATH: _test(*lines) + TWO_CLAIMS})
    return _run(root, _policy())


F = Finding(f"{PATH}::test_f", MESSAGE)


class TestCounting:
    def test_one_assert_passes(self, repo: RepoFactory) -> None:
        assert _judge(repo, "assert run() == 1") == [BAD]

    def test_two_asserts_fail(self, repo: RepoFactory) -> None:
        assert _judge(repo, "assert run() == 1", "assert run() == 2") == [BAD, F]

    def test_asserts_deep_in_blocks_count(self, repo: RepoFactory) -> None:
        lines = ["assert run() == 1", "for x in xs:", "    assert x == 2"]
        assert _judge(repo, *lines) == [BAD, F]

    def test_asserts_inside_a_raises_block_count(self, repo: RepoFactory) -> None:
        lines = ["with pytest.raises(E):", "    assert run() == 1", "assert log == 2"]
        assert _judge(repo, *lines) == [BAD, F]

    def test_assert_in_a_nested_def_is_not_the_tests(self, repo: RepoFactory) -> None:
        lines = ["def check(x):", "    assert x == 1", "assert run() == 2"]
        assert _judge(repo, *lines) == [BAD]

    def test_raises_and_assert_calls_are_not_counted(self, repo: RepoFactory) -> None:
        lines = [
            "with pytest.raises(E):",
            "    run(bad)",
            "mock.assert_called_once_with(1)",
            "assert run() == 2",
        ]
        assert _judge(repo, *lines) == [BAD]

    def test_packed_tuple_assertion_is_one_claim(self, repo: RepoFactory) -> None:
        assert _judge(repo, "assert (run(a), run(b)) == ([], [1])") == [BAD]

    def test_test_with_no_assert_passes(self, repo: RepoFactory) -> None:
        assert _judge(repo, "run()") == [BAD]


class TestNarrowingGuards:
    @pytest.mark.parametrize(("guard", "subject"), GUARDS)
    def test_guard_before_a_claim_on_its_subject_is_no_claim(
        self, repo: RepoFactory, guard: str, subject: str
    ) -> None:
        lines = ["out = run()", f"assert {guard}", f"assert {subject}.x == 3"]
        assert _judge(repo, *lines) == [BAD]

    def test_guard_whose_subject_a_later_statement_reads_is_no_claim(
        self, repo: RepoFactory
    ) -> None:
        lines = ["assert out is not None", "code = out.code", "assert code == 3"]
        assert _judge(repo, *lines) == [BAD]

    def test_guard_whose_subject_is_not_read_again_is_a_claim(
        self, repo: RepoFactory
    ) -> None:
        lines = ["assert out is not None", "assert other == 3"]
        assert _judge(repo, *lines) == [BAD, F]

    def test_last_guard_is_a_claim_that_the_guard_before_it_narrows_for(
        self, repo: RepoFactory
    ) -> None:
        lines = ["assert out is not None", "assert isinstance(out, Result)"]
        assert _judge(repo, *lines) == [BAD]

    def test_guard_after_the_last_claim_is_a_claim(self, repo: RepoFactory) -> None:
        lines = ["assert out.x == 3", "assert out is not None", "print(out)"]
        assert _judge(repo, *lines) == [BAD, F]

    @pytest.mark.parametrize(
        "guard",
        ["out != None", "out is not 0", "isinstance(out)", "run() is not None"],
    )
    def test_other_shapes_are_claims(self, repo: RepoFactory, guard: str) -> None:
        lines = ["out = run()", f"assert {guard}", "assert out.x == 3"]
        assert _judge(repo, *lines) == [BAD, F]

    def test_several_guards_before_one_claim_pass(self, repo: RepoFactory) -> None:
        lines = [
            "assert out is not None",
            "assert out.body is not None",
            "assert out.body.x == 3",
        ]
        assert _judge(repo, *lines) == [BAD]


class TestExemptions:
    def test_exempt_test_passes(self, repo: RepoFactory) -> None:
        root = repo({PATH: TWO_CLAIMS})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={f"{PATH}::test_bad": "the contract"}))
        assert (plain, exempt) == ([BAD], [])

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == 3")})
        key = "tests/test_gone.py::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [_stale(key, "names no file")]

    def test_entry_naming_no_test_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: TWO_CLAIMS})
        key = f"{PATH}::test_gone"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "names no test"),
            BAD,
        ]

    def test_entry_on_a_test_of_one_claim_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == 3")})
        key = f"{PATH}::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "makes one claim, so it needs no exemption")
        ]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "claims"],
        [gate.name for gate in off if gate.name == "claims"],
    ) == ([ClaimsGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({PATH: TWO_CLAIMS})
    policy = _policy()
    state = State()
    assert ClaimsGate().accept(build_tree(root, policy), policy, state) is state
