"""Tests for filepawl.gates.handlers: the handlers gate (design.md §6.10)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import Policy, default_policy
from filepawl.config_code import HandlersPolicy
from filepawl.gates.base import Finding
from filepawl.gates.handlers import HandlersGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

VALUE_IN_HANDLER = (
    "def f():\n" "    try:\n" "        g()\n" "    except E:\n" "        return 1\n"
)


def _lines(*lines: int) -> str:
    where = "line" if len(lines) == 1 else "lines"
    spelled = ", ".join(str(line) for line in lines)
    return f"hands the caller a value from an except handler at {where} {spelled}" + (
        " — let it propagate, raise a narrower one, or handle it"
        " so nothing returned stands for the failure"
    )


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.handlers.exempt] {key!r}: {message}"
    )


def _policy(**handlers: object) -> Policy:
    return dataclasses.replace(
        default_policy(), handlers=HandlersPolicy(**handlers)  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return HandlersGate().run(build_tree(root, policy), policy, State())


class TestValueReturns:
    def test_value_return_in_except_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_return_none_in_except_fails(self, repo: RepoFactory) -> None:
        source = VALUE_IN_HANDLER.replace("return 1", "return None")
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_value_return_in_except_star_fails(self, repo: RepoFactory) -> None:
        source = VALUE_IN_HANDLER.replace("except E", "except* E")
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_no_handler_return_passes(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        return g()\n"
            "    except E:\n"
            "        log()\n"
            "        raise\n"
            "    else:\n"
            "        return 2\n"
            "    finally:\n"
            "        return 3\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_return_deep_inside_handler_counts(self, repo: RepoFactory) -> None:
        source = (
            "def f(xs):\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        for x in xs:\n"
            "            if x:\n"
            "                with x:\n"
            "                    return x\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(8))]

    def test_try_nested_in_handler_counts_in_every_branch(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        try:\n"
            "            return 1\n"
            "        except F:\n"
            "            pass\n"
            "        else:\n"
            "            return 2\n"
            "        finally:\n"
            "            return 3\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(6, 10, 12))]

    def test_every_failing_return_is_listed_in_source_order(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return 1\n"
            "    except F:\n"
            "        return 2\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5, 7))]


class TestBareReturns:
    def test_bare_return_alone_passes(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return\n"
            "    h()\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_bare_return_beside_value_return_fails(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return\n"
            "    return h()\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_bare_return_beside_return_none_fails(self, repo: RepoFactory) -> None:
        source = (
            "def f(c):\n"
            "    if c:\n"
            "        return None\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(7))]

    def test_bare_and_value_returns_in_handlers_are_listed(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return\n"
            "    except F:\n"
            "        return 0\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5, 7))]


class TestHandlerAssignments:
    def test_name_assigned_in_handler_and_returned_fails(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        result = g()\n"
            "    except E:\n"
            "        result = {}\n"
            "    return result\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_name_read_anywhere_in_returned_value_fails(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    warning = None\n"
            "    try:\n"
            "        g()\n"
            "    except E as exc:\n"
            "        warning = str(exc)\n"
            "    return Outcome(done=True, warning=warning)\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(6))]

    def test_name_assigned_in_handler_but_not_returned_passes(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E as exc:\n"
            "        detail = str(exc)\n"
            "        log(detail)\n"
            "        raise\n"
            "    return h()\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_handler_assignment_without_value_return_passes(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        done = False\n"
            "        return\n"
            "    h(done)\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_every_assignment_form_binds_a_name(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        a, (b, *c) = g()\n"
            "    except E:\n"
            "        a, (b, *c) = 1, (2, 3)\n"
            "    except F:\n"
            "        n: int = 0\n"
            "    except G:\n"
            "        n += 1\n"
            "    return a + b + len(c) + n\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5, 7, 9))]

    def test_attribute_and_subscript_targets_bind_no_name(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f(self, out):\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        self.failed = True\n"
            "        out['error'] = 1\n"
            "    return self, out\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_assignment_deep_inside_handler_counts(self, repo: RepoFactory) -> None:
        source = (
            "def f(xs):\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        for x in xs:\n"
            "            if x:\n"
            "                found = x\n"
            "    return found\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(7))]

    def test_nested_def_and_class_in_handler_bind_nothing_for_outer(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    x = 1\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        def inner():\n"
            "            x = 2\n"
            "            h(x)\n"
            "        class C:\n"
            "            x = 3\n"
            "    return x\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_returns_and_assignments_are_listed_in_source_order(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        return 0\n"
            "    except F:\n"
            "        v = 1\n"
            "    return v\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5, 7))]

    def test_exemption_covers_a_handler_assignment(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        v = g()\n"
            "    except E:\n"
            "        v = 0\n"
            "    return v\n"
        )
        root = repo({"m.py": source})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={"m.py::f": "r"}))
        assert (plain, exempt) == ([Finding("m.py::f", _lines(5))], [])


class TestFunctions:
    def test_nested_def_in_handler_is_judged_on_its_own(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def outer():\n"
            "    try:\n"
            "        g()\n"
            "    except E:\n"
            "        def inner():\n"
            "            return 1\n"
            "        inner()\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_nested_value_return_does_not_count_for_outer(
        self, repo: RepoFactory
    ) -> None:
        source = (
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "    try:\n"
            "        inner()\n"
            "    except E:\n"
            "        return\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_nested_def_fails_under_its_own_name(self, repo: RepoFactory) -> None:
        source = "def outer():\n" + "".join(
            "    " + line + "\n" for line in VALUE_IN_HANDLER.splitlines()
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::outer.f", _lines(6))]

    def test_lambda_gives_outer_no_value_return(self, repo: RepoFactory) -> None:
        source = (
            "def f():\n"
            "    key = lambda x: x\n"
            "    try:\n"
            "        g(key)\n"
            "    except E:\n"
            "        return\n"
        )
        root = repo({"m.py": source, "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]

    def test_method_and_async_function_are_checked(self, repo: RepoFactory) -> None:
        source = (
            "class C:\n"
            "    async def m(self):\n"
            "        try:\n"
            "            await g()\n"
            "        except E:\n"
            "            return 0\n"
        )
        root = repo({"m.py": source})
        assert _run(root, _policy()) == [Finding("m.py::C.m", _lines(6))]


class TestFileSet:
    def test_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": VALUE_IN_HANDLER, "m.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("m.py::f", _lines(5))]

    def test_files_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"a/m.py": VALUE_IN_HANDLER, "b/m.py": VALUE_IN_HANDLER})
        assert _run(root, _policy(include=("a/**",))) == [
            Finding("a/m.py::f", _lines(5))
        ]

    def test_file_that_does_not_parse_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f(:\n", "n.py": VALUE_IN_HANDLER})
        assert _run(root, _policy()) == [Finding("n.py::f", _lines(5))]


class TestExemptions:
    def test_exempt_function_passes(self, repo: RepoFactory) -> None:
        root = repo({"m.py": VALUE_IN_HANDLER})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={"m.py::f": "CLI boundary"}))
        assert (plain, exempt) == ([Finding("m.py::f", _lines(5))], [])

    def test_entry_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "x = 1\n"})
        policy = _policy(exempt={"gone.py::f": "r"})
        assert _run(root, policy) == [_stale("gone.py::f", "names no file")]

    def test_entry_naming_a_test_path_names_no_file(self, repo: RepoFactory) -> None:
        root = repo({"tests/test_m.py": VALUE_IN_HANDLER})
        policy = _policy(exempt={"tests/test_m.py::f": "r"})
        assert _run(root, policy) == [_stale("tests/test_m.py::f", "names no file")]

    def test_entry_naming_no_function_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": VALUE_IN_HANDLER})
        policy = _policy(exempt={"m.py::g": "r"})
        assert _run(root, policy) == [
            Finding("m.py::f", _lines(5)),
            _stale("m.py::g", "names no function"),
        ]

    def test_entry_on_clean_function_fails(self, repo: RepoFactory) -> None:
        root = repo({"m.py": "def f():\n    return 1\n"})
        policy = _policy(exempt={"m.py::f": "r"})
        assert _run(root, policy) == [
            _stale(
                "m.py::f",
                "hands the caller no value from a handler, so it needs no exemption",
            )
        ]

    def test_entry_covers_every_function_its_key_names(self, repo: RepoFactory) -> None:
        source = VALUE_IN_HANDLER + "def f():\n    return 1\n"
        root = repo({"m.py": source})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(exempt={"m.py::f": "r"}))
        assert (plain, exempt) == ([Finding("m.py::f", _lines(5))], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({"m.py": VALUE_IN_HANDLER})
    policy = _policy()
    state = State()
    assert HandlersGate().accept(build_tree(root, policy), policy, state) is state
