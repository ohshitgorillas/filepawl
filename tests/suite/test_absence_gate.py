"""Tests for filepawl.gates.suite.absence: the absence gate (design.md §6.11)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import AbsencePolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.absence import AbsenceGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

MESSAGE = (
    "asserts only an absent value — code that never ran the feature passes"
    " it too; assert it beside a case where the feature acts"
)

PATH = "tests/test_m.py"

#: A test that fails the gate, set beside a passing case so the same run
#: shows the gate acting.
ABSENT_ONLY = "def test_bad():\n    assert run() == []\n"
BAD = Finding(f"{PATH}::test_bad", MESSAGE)

ABSENT_VALUES = [
    "None",
    "False",
    "0",
    "0.0",
    '""',
    'b""',
    "[]",
    "{}",
    "()",
    "(None, 0, '')",
    "list()",
    "dict()",
    "set()",
    "tuple()",
    "frozenset()",
    "str()",
    "bytes()",
]

PRESENT_VALUES = [
    "True",
    "1",
    "'x'",
    "[1]",
    "{'a': 1}",
    "(0, 1)",
    "(None, [1])",
    "list([1])",
    "dict(a=1)",
    "set(xs)",
    "{0}",
    "Result()",
]


def _test(*lines: str, name: str = "test_f") -> str:
    return f"def {name}():\n" + "".join(f"    {line}\n" for line in lines)


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.absence.exempt] {key!r}: {message}"
    )


def _policy(**absence: object) -> Policy:
    suite = SuitePolicies(absence=AbsencePolicy(**absence))  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=suite)


def _run(root: Path, policy: Policy) -> list[Finding]:
    return AbsenceGate().run(build_tree(root, policy), policy, State())


def _judge(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines` beside a test that fails."""
    root = repo({PATH: _test(*lines) + ABSENT_ONLY})
    return _run(root, _policy())


def _fails(repo: RepoFactory, *lines: str) -> list[Finding]:
    """Run the gate over one test of `lines` alone."""
    root = repo({PATH: _test(*lines)})
    return _run(root, _policy())


F = Finding(f"{PATH}::test_f", MESSAGE)


class TestAbsentValues:
    @pytest.mark.parametrize("value", ABSENT_VALUES)
    @pytest.mark.parametrize("op", ["==", "is"])
    def test_absent_value_on_the_right_fails(
        self, repo: RepoFactory, value: str, op: str
    ) -> None:
        assert _fails(repo, f"assert run() {op} {value}") == [F]

    @pytest.mark.parametrize("value", ABSENT_VALUES)
    @pytest.mark.parametrize("op", ["==", "is"])
    def test_absent_value_on_the_left_fails(
        self, repo: RepoFactory, value: str, op: str
    ) -> None:
        assert _fails(repo, f"assert {value} {op} run()") == [F]

    def test_not_fails(self, repo: RepoFactory) -> None:
        assert _fails(repo, "assert not run()") == [F]

    def test_len_equal_to_zero_fails(self, repo: RepoFactory) -> None:
        assert _fails(repo, "assert len(run()) == 0") == [F]

    def test_every_assert_absent_fails(self, repo: RepoFactory) -> None:
        lines = ["out = run()", "assert out.code == 0", "assert not out.err"]
        assert _fails(repo, *lines) == [F]

    def test_asserts_inside_blocks_are_the_tests(self, repo: RepoFactory) -> None:
        lines = [
            "for x in xs:",
            "    if x:",
            "        with ctx():",
            "            assert run(x) is None",
            "    else:",
            "        try:",
            "            assert run(x) == []",
            "        except E:",
            "            assert not x",
        ]
        assert _fails(repo, *lines) == [F]


class TestPresentValues:
    @pytest.mark.parametrize("value", PRESENT_VALUES)
    def test_present_value_passes(self, repo: RepoFactory, value: str) -> None:
        assert _judge(repo, f"assert run() == {value}") == [BAD]

    def test_pair_of_absent_and_present_passes(self, repo: RepoFactory) -> None:
        assert _judge(repo, "assert (run(a), run(b)) == ([], [finding])") == [BAD]

    @pytest.mark.parametrize(
        "test",
        [
            "run() != []",
            "run() is not None",
            "'text' in run()",
            "[] in run()",
            "run()",
            "0 == run() == 0",
            "0 < run()",
        ],
    )
    def test_other_assertions_pass(self, repo: RepoFactory, test: str) -> None:
        assert _judge(repo, f"assert {test}") == [BAD]

    def test_one_present_assertion_among_absent_ones_passes(
        self, repo: RepoFactory
    ) -> None:
        lines = ["assert run(a) == []", "assert run(b) == [1]", "assert not err"]
        assert _judge(repo, *lines) == [BAD]


class TestAssertingSomethingElse:
    @pytest.mark.parametrize(
        "context",
        [
            "pytest.raises(E)",
            "pytest.warns(W)",
            "pytest.deprecated_call()",
            "ctx(), pytest.raises(E, match='x')",
        ],
    )
    def test_raises_warns_and_deprecated_call_contexts_pass(
        self, repo: RepoFactory, context: str
    ) -> None:
        lines = ["assert run() == []", f"with {context}:", "    run(bad)"]
        assert _judge(repo, *lines) == [BAD]

    @pytest.mark.parametrize(
        "call",
        ["self.assertEqual(run(), [])", "mock.assert_called_once_with(1)"],
    )
    def test_assert_method_call_passes(self, repo: RepoFactory, call: str) -> None:
        assert _judge(repo, "assert run() == []", call) == [BAD]

    def test_other_context_does_not_count(self, repo: RepoFactory) -> None:
        lines = ["with ctx():", "    assert run() == []"]
        assert _fails(repo, *lines) == [F]

    def test_bare_name_raises_does_not_count(self, repo: RepoFactory) -> None:
        lines = ["assert run() == []", "with raises(E):", "    run(bad)"]
        assert _fails(repo, *lines) == [F]


class TestWhatIsATest:
    def test_test_with_no_assert_passes(self, repo: RepoFactory) -> None:
        assert _judge(repo, "run()") == [BAD]

    def test_assert_in_nested_def_is_not_the_tests(self, repo: RepoFactory) -> None:
        lines = [
            "def check():",
            "    assert run() == [1]",
            "assert run() == []",
        ]
        assert _fails(repo, *lines) == [F]

    def test_nested_def_alone_leaves_the_test_with_no_assert(
        self, repo: RepoFactory
    ) -> None:
        lines = ["def check():", "    assert run() == []", "check()"]
        assert _judge(repo, *lines) == [BAD]

    def test_assert_in_nested_class_is_not_the_tests(self, repo: RepoFactory) -> None:
        lines = [
            "class Probe:",
            "    def check(self):",
            "        assert run() == [1]",
            "assert run() == []",
        ]
        assert _fails(repo, *lines) == [F]

    def test_assert_call_in_lambda_is_not_the_tests(self, repo: RepoFactory) -> None:
        lines = ["check = lambda m: m.assert_called()", "assert run() == []"]
        assert _fails(repo, *lines) == [F]

    def test_async_test_is_checked(self, repo: RepoFactory) -> None:
        source = "async def test_a():\n    assert await run() is None\n"
        root = repo({PATH: source})
        assert _run(root, _policy()) == [Finding(f"{PATH}::test_a", MESSAGE)]

    def test_test_class_methods_are_named_by_qualified_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "class TestThing:\n"
            "    def test_a(self):\n"
            "        assert run() == []\n"
            "    async def test_b(self):\n"
            "        assert not run()\n"
        )
        root = repo({PATH: source})
        assert _run(root, _policy()) == [
            Finding(f"{PATH}::TestThing.test_a", MESSAGE),
            Finding(f"{PATH}::TestThing.test_b", MESSAGE),
        ]

    def test_non_tests_are_not_judged(self, repo: RepoFactory) -> None:
        source = (
            "def helper():\n"
            "    assert run() == []\n"
            "class Helper:\n"
            "    def test_a(self):\n"
            "        assert run() == []\n"
            "class TestOuter:\n"
            "    def helper(self):\n"
            "        assert run() == []\n"
            "    class TestInner:\n"
            "        def test_a(self):\n"
            "            assert run() == []\n"
            "def outer():\n"
            "    def test_inner():\n"
            "        assert run() == []\n"
        )
        root = repo({PATH: source + ABSENT_ONLY})
        assert _run(root, _policy()) == [BAD]


class TestFileSet:
    def test_non_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"pkg/test_m.py": ABSENT_ONLY, PATH: ABSENT_ONLY})
        assert _run(root, _policy()) == [BAD]

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/unit/test_m.py": ABSENT_ONLY, PATH: ABSENT_ONLY})
        assert _run(root, _policy(include=("tests/test_*.py",))) == [BAD]

    def test_test_globs_come_from_policy(self, repo: RepoFactory) -> None:
        root = repo({"spec/test_m.py": ABSENT_ONLY, PATH: ABSENT_ONLY})
        policy = dataclasses.replace(_policy(), tests=("spec/**",))
        assert _run(root, policy) == [Finding("spec/test_m.py::test_bad", MESSAGE)]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_broken.py": "def test_(:\n", PATH: ABSENT_ONLY})
        assert _run(root, _policy()) == [BAD]


class TestExemptions:
    def test_exempt_test_passes(self, repo: RepoFactory) -> None:
        root = repo({PATH: ABSENT_ONLY})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={f"{PATH}::test_bad": "silence"}))
        assert (plain, exempt) == ([BAD], [])

    def test_exempt_method_is_keyed_by_qualified_name(self, repo: RepoFactory) -> None:
        source = "class TestT:\n    def test_a(self):\n        assert not run()\n"
        root = repo({PATH: source})
        key = f"{PATH}::TestT.test_a"
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={key: "silence"}))
        assert (plain, exempt) == ([Finding(key, MESSAGE)], [])

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == [1]")})
        key = "tests/test_gone.py::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [_stale(key, "names no file")]

    def test_entry_naming_a_non_test_path_names_no_file(
        self, repo: RepoFactory
    ) -> None:
        root = repo({"pkg/m.py": ABSENT_ONLY})
        key = "pkg/m.py::test_bad"
        assert _run(root, _policy(exempt={key: "r"})) == [_stale(key, "names no file")]

    def test_entry_naming_no_test_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: ABSENT_ONLY})
        key = f"{PATH}::test_gone"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "names no test"),
            BAD,
        ]

    def test_entry_on_a_present_assertion_fails(self, repo: RepoFactory) -> None:
        root = repo({PATH: _test("assert run() == [1]")})
        key = f"{PATH}::test_f"
        assert _run(root, _policy(exempt={key: "r"})) == [
            _stale(key, "asserts a present value, so it needs no exemption")
        ]


def test_gate_is_the_last_built_in() -> None:
    assert registry._BUILTIN_GATES[-1] == (
        "absence",
        "filepawl.gates.suite.absence",
        "AbsenceGate",
    )


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({PATH: ABSENT_ONLY})
    policy = _policy()
    state = State()
    assert AbsenceGate().accept(build_tree(root, policy), policy, state) is state
