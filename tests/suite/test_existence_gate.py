"""Tests for filepawl.gates.suite.existence: the existence gate (design.md §6.18)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SuiteGatePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.existence import ExistenceGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

MESSAGE = (
    "asserts only that a value exists — a stub returning any value passes it"
    " too; assert the value"
)

PATH = "tests/test_m.py"

#: A test that fails the gate, set beside a passing case so the same run
#: shows the gate acting.
EXISTS_ONLY = "def test_bad():\n    assert isinstance(run(), Result)\n"
BAD = Finding(f"{PATH}::test_bad", MESSAGE)

EXISTENCE_FORMS = [
    "out",
    "out.items",
    "out[0]",
    "isinstance(out, Result)",
    "issubclass(Out, Base)",
    "callable(out)",
    "hasattr(out, 'x')",
    "bool(out)",
    "len(out)",
    "out is not None",
    "None is not out",
    "out != []",
    "'' != out",
    "len(out) > 0",
    "len(out) >= 1",
    "0 < len(out)",
    "1 <= len(out)",
    "'k' in out.keys()",
    "'k' in vars(out)",
    "'k' in dir(out)",
    "type(out) == Result",
    "Result is type(out)",
]


def _test(*lines: str, name: str = "test_f") -> str:
    return f"def {name}():\n" + "".join(f"    {line}\n" for line in lines)


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.existence.exempt] {key!r}: {message}"
    )


def _policy(**existence: object) -> Policy:
    table = SuiteGatePolicy(**existence)  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=SuitePolicies(existence=table))


def _run(root: Path, policy: Policy) -> list[Finding]:
    return ExistenceGate().run(build_tree(root, policy), policy, State())


def _judge(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines` beside a test that fails."""
    root = repo({PATH: _test(*lines) + EXISTS_ONLY})
    return _run(root, _policy())


def _fails(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines` alone."""
    root = repo({PATH: _test(*lines)})
    return _run(root, _policy())


F = Finding(f"{PATH}::test_f", MESSAGE)


class TestExistenceForms:
    @pytest.mark.parametrize("form", EXISTENCE_FORMS)
    def test_existence_form_alone_fails(self, repo: RepoFactory, form: str) -> None:
        assert _fails(repo, "out = run()", f"assert {form}") == [F]

    @pytest.mark.parametrize("form", EXISTENCE_FORMS)
    def test_existence_form_beside_absence_assertions_fails(
        self, repo: RepoFactory, form: str
    ) -> None:
        lines = ["out = run()", "assert run(bad) == []", f"assert {form}"]
        assert _fails(repo, *lines) == [F]

    @pytest.mark.parametrize(
        "test",
        [
            "out == Result(1)",
            "out > 2",
            "len(out) == 3",
            "'k' in out",
            "out != other",
            "type(out, extra) == Result",
            "run()",
            "len(out) > 0.0",
            "len(out) > True",
        ],
    )
    def test_value_assertion_passes(self, repo: RepoFactory, test: str) -> None:
        assert _judge(repo, "out = run()", f"assert {test}") == [BAD]

    def test_existence_beside_a_value_assertion_passes(self, repo: RepoFactory) -> None:
        lines = ["out = run()", "assert out is not None", "assert out.code == 3"]
        assert _judge(repo, *lines) == [BAD]

    def test_every_assert_absent_is_left_to_the_absence_gate(
        self, repo: RepoFactory
    ) -> None:
        assert _judge(repo, "assert run() == []", "assert not err") == [BAD]


class TestPackedAssertions:
    @pytest.mark.parametrize(
        "test",
        [
            "(out != [], chips(page)) == (True, [])",
            "(type(err), err == '') == (str, False)",
            "(out is None, err) == (False, None)",
            "(a, (isinstance(out, R), b)) == (None, (True, None))",
        ],
    )
    def test_packed_existence_and_absence_pairs_fail(
        self, repo: RepoFactory, test: str
    ) -> None:
        assert _fails(repo, "out = run()", f"assert {test}") == [F]

    @pytest.mark.parametrize(
        "test",
        [
            "(out != [], chips(page)) == (True, ['a'])",
            "(failed, succeeded) == (False, True)",
            "(type(err), err) == (str, 'boom')",
            "(out is not None, err) == (True, None, 0)",
        ],
    )
    def test_packed_assertion_with_a_value_pair_passes(
        self, repo: RepoFactory, test: str
    ) -> None:
        assert _judge(repo, "out = run()", f"assert {test}") == [BAD]


class TestWhatCounts:
    def test_raises_context_counts_as_asserting_something_else(
        self, repo: RepoFactory
    ) -> None:
        lines = ["assert run()", "with pytest.raises(E):", "    run(bad)"]
        assert _judge(repo, *lines) == [BAD]

    def test_test_with_no_assert_passes(self, repo: RepoFactory) -> None:
        assert _judge(repo, "run()") == [BAD]

    def test_test_class_methods_are_named_by_qualified_name(
        self, repo: RepoFactory
    ) -> None:
        source = "class TestThing:\n    def test_a(self):\n        assert run().items\n"
        root = repo({PATH: source})
        key = f"{PATH}::TestThing.test_a"
        assert _run(root, _policy()) == [Finding(key, MESSAGE)]

    def test_non_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"pkg/test_m.py": EXISTS_ONLY, PATH: EXISTS_ONLY})
        assert _run(root, _policy()) == [BAD]

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/unit/test_m.py": EXISTS_ONLY, PATH: EXISTS_ONLY})
        assert _run(root, _policy(include=("tests/test_*.py",))) == [BAD]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_broken.py": "def test_(:\n", PATH: EXISTS_ONLY})
        assert _run(root, _policy()) == [BAD]


class TestExemptions:
    def test_exempt_test_passes(self, repo: RepoFactory) -> None:
        root = repo({PATH: EXISTS_ONLY})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={f"{PATH}::test_bad": "the contract"}))
        assert (plain, exempt) == ([BAD], [])

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == 3")})
        key = "tests/test_gone.py::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [_stale(key, "names no file")]

    def test_entry_naming_no_test_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: EXISTS_ONLY})
        key = f"{PATH}::test_gone"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "names no test"),
            BAD,
        ]

    def test_entry_on_a_value_assertion_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == 3")})
        key = f"{PATH}::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "asserts a value, so it needs no exemption")
        ]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "existence"],
        [gate.name for gate in off if gate.name == "existence"],
    ) == ([ExistenceGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({PATH: EXISTS_ONLY})
    policy = _policy()
    state = State()
    assert ExistenceGate().accept(build_tree(root, policy), policy, state) is state
