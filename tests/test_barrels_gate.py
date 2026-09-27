"""Tests for filepawl.gates.barrels: the barrels gate (design.md §6.6)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from filepawl.config import Policy, default_policy
from filepawl.config_code import BarrelsPolicy
from filepawl.gates.barrels import BarrelsGate
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

REEXPORT = "imports and defines nothing — a re-export module is not a split"
FORWARDER = "returns a call on its own arguments — move the callers, not the method"

FORWARDING_METHOD = (
    "class A:\n"
    "    def f(self, x):\n"
    '        """Doc."""\n'
    "        return self._other.f(x)\n"
)


def _policy(**barrels: object) -> Policy:
    return dataclasses.replace(
        default_policy(), barrels=BarrelsPolicy(**barrels)  # type: ignore[arg-type]
    )


def _run(root: Path, policy: Policy) -> list[Finding]:
    return BarrelsGate().run(build_tree(root, policy), policy, State())


class TestReexportModule:
    def test_imports_only_fails(self, repo: RepoFactory) -> None:
        root = repo({"pkg/shim.py": "from pkg.real import *\n"})
        assert _run(root, _policy()) == [Finding("pkg/shim.py", REEXPORT)]

    def test_imports_and_all_manifest_fails(self, repo: RepoFactory) -> None:
        root = repo({"shim.py": "from real import f\n__all__ = ['f']\n"})
        assert _run(root, _policy()) == [Finding("shim.py", REEXPORT)]

    def test_imports_and_constant_passes(self, repo: RepoFactory) -> None:
        root = repo(
            {"m.py": "from real import f\nLIMIT = 3\n", "shim.py": "import os\n"}
        )
        assert _run(root, _policy()) == [Finding("shim.py", REEXPORT)]

    def test_imports_and_main_guard_only_fails(self, repo: RepoFactory) -> None:
        source = "import sys\nif __name__ == '__main__':\n    sys.exit(0)\n"
        root = repo({"tool.py": source})
        assert _run(root, _policy()) == [Finding("tool.py", REEXPORT)]

    def test_package_init_of_imports_passes(self, repo: RepoFactory) -> None:
        source = "from pkg.real import f\n"
        root = repo({"pkg/__init__.py": source, "pkg/shim.py": source})
        assert _run(root, _policy()) == [Finding("pkg/shim.py", REEXPORT)]

    def test_empty_module_passes(self, repo: RepoFactory) -> None:
        root = repo({"m.py": '"""Nothing."""\n', "shim.py": "import os\n"})
        assert _run(root, _policy()) == [Finding("shim.py", REEXPORT)]

    def test_test_paths_are_not_checked(self, repo: RepoFactory) -> None:
        source = "from pkg.real import *\n"
        root = repo({"tests/helpers.py": source, "pkg/shim.py": source})
        assert _run(root, _policy()) == [Finding("pkg/shim.py", REEXPORT)]

    def test_paths_outside_include_are_not_checked(self, repo: RepoFactory) -> None:
        root = repo({"other/shim.py": "import os\n", "pkg/shim.py": "import os\n"})
        findings = _run(root, _policy(include=("pkg/**/*.py",)))
        assert findings == [Finding("pkg/shim.py", REEXPORT)]

    def test_exempt_module_passes(self, repo: RepoFactory) -> None:
        root = repo({"shim.py": "import os\n"})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(module_exempt={"shim.py": "why"}))
        assert (plain, exempt) == ([Finding("shim.py", REEXPORT)], [])


class TestForwarder:
    def test_method_forwarding_its_parameters_fails(self, repo: RepoFactory) -> None:
        root = repo({"a.py": FORWARDING_METHOD})
        assert _run(root, _policy()) == [Finding("a.py::f", FORWARDER)]

    def test_awaited_forwarder_fails(self, repo: RepoFactory) -> None:
        source = "async def f(client, x):\n    return await client.get(x)\n"
        root = repo({"a.py": source})
        assert _run(root, _policy()) == [Finding("a.py::f", FORWARDER)]

    def test_module_rooted_forwarder_fails(self, repo: RepoFactory) -> None:
        root = repo({"a.py": "import real\ndef f(x):\n    return real.f(x)\n"})
        assert _run(root, _policy()) == [Finding("a.py::f", FORWARDER)]

    def test_reordered_arguments_pass(self, repo: RepoFactory) -> None:
        source = "def f(self, a, b):\n    return self.o.f(b, a)\n"
        root = repo({"a.py": source, "b.py": FORWARDING_METHOD})
        assert _run(root, _policy()) == [Finding("b.py::f", FORWARDER)]

    def test_keyword_argument_passes(self, repo: RepoFactory) -> None:
        source = "def f(self, a):\n    return self.o.f(a, scope=1)\n"
        root = repo({"a.py": source, "b.py": FORWARDING_METHOD})
        assert _run(root, _policy()) == [Finding("b.py::f", FORWARDER)]

    def test_work_before_return_passes(self, repo: RepoFactory) -> None:
        source = "def f(self, a):\n    a += 1\n    return self.o.f(a)\n"
        root = repo({"a.py": source, "b.py": FORWARDING_METHOD})
        assert _run(root, _policy()) == [Finding("b.py::f", FORWARDER)]

    def test_call_rooted_chain_passes(self, repo: RepoFactory) -> None:
        source = "def f(self, a):\n    return self.http().restore(a)\n"
        root = repo({"a.py": source, "b.py": FORWARDING_METHOD})
        assert _run(root, _policy()) == [Finding("b.py::f", FORWARDER)]

    def test_outside_forwarders_scope_passes(self, repo: RepoFactory) -> None:
        root = repo({"api/a.py": FORWARDING_METHOD, "core/b.py": FORWARDING_METHOD})
        findings = _run(root, _policy(forwarders=("core/**",)))
        assert findings == [Finding("core/b.py::f", FORWARDER)]

    def test_exempt_forwarder_passes(self, repo: RepoFactory) -> None:
        root = repo({"a.py": FORWARDING_METHOD})
        plain = _run(root, _policy())
        exempt = _run(root, _policy(forwarder_exempt={"a.py::f": "facade"}))
        assert (plain, exempt) == ([Finding("a.py::f", FORWARDER)], [])


class TestStaleExemptions:
    def test_module_exemption_naming_no_file_fails(self, repo: RepoFactory) -> None:
        root = repo({"a.py": "X = 1\n"})
        findings = _run(root, _policy(module_exempt={"gone.py": "why"}))
        assert findings == [
            Finding(
                "pyproject.toml",
                "[tool.filepawl.barrels.module_exempt] 'gone.py': names no file",
            )
        ]

    def test_module_exemption_on_defining_module_fails(self, repo: RepoFactory) -> None:
        root = repo({"a.py": "X = 1\n"})
        findings = _run(root, _policy(module_exempt={"a.py": "why"}))
        assert findings == [
            Finding(
                "pyproject.toml",
                "[tool.filepawl.barrels.module_exempt] 'a.py': "
                "the module defines something, so it needs no exemption",
            )
        ]

    def test_forwarder_exemption_matching_nothing_fails(
        self, repo: RepoFactory
    ) -> None:
        root = repo({"a.py": FORWARDING_METHOD})
        findings = _run(
            root,
            _policy(forwarder_exempt={"a.py::f": "facade", "a.py::g": "gone"}),
        )
        assert findings == [
            Finding(
                "pyproject.toml",
                "[tool.filepawl.barrels.forwarder_exempt] 'a.py::g': "
                "matches no forwarder",
            )
        ]

    def test_audit_ignores_argv_narrowing(self, repo: RepoFactory) -> None:
        root = repo({"a.py": FORWARDING_METHOD, "b.py": "X = 1\n"})
        live = _policy(forwarder_exempt={"a.py::f": "facade"})
        stale = _policy(forwarder_exempt={"a.py::f": "facade", "a.py::g": "gone"})
        runs = [
            BarrelsGate().run(build_tree(root, policy, ["b.py"]), policy, State())
            for policy in (live, stale)
        ]
        assert runs == [
            [],
            [
                Finding(
                    "pyproject.toml",
                    "[tool.filepawl.barrels.forwarder_exempt] 'a.py::g': "
                    "matches no forwarder",
                )
            ],
        ]


class TestGateShape:
    def test_unparseable_file_is_skipped(self, repo: RepoFactory) -> None:
        root = repo({"a.py": "def (:\n", "shim.py": "import os\n"})
        assert _run(root, _policy()) == [Finding("shim.py", REEXPORT)]

    def test_accept_is_identity(self, repo: RepoFactory) -> None:
        root = repo({"a.py": "X = 1\n"})
        policy = _policy()
        state = State()
        tree = build_tree(root, policy)
        assert BarrelsGate().accept(tree, policy, state) is state
