"""Port of Gauntlet's barrel-gate self-test to filepawl's barrels gate.

Source: ``~/dev/gauntlet/scripts/gates/code/no_barrels_selftest.py``. Each
test cites the ``check(...)`` rule strings it ports; where the source checks a
status and a stdout line from one run, the port asserts the findings of that
run once. The source keeps its self-picked file set to ``hooks/`` and
``scripts/`` and checks rule 2 everywhere, which is expressed here as the
policy's ``include`` and ``forwarders`` scope.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from filepawl.config import Policy, default_policy
from filepawl.config_code import BarrelsPolicy
from filepawl.gates.barrels import BarrelsGate
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

REEXPORT = "import os\nimport sys\n"
DEFINES_FUNCTION = 'import os\n\n\ndef f():\n    return os.sep + "x"\n'
DEFINES_CONSTANT = "import os\n\nROOT = os.sep\n"
ONLY_ALL = 'import os\n\n__all__ = ["os"]\n'
ONLY_MAIN_GUARD = 'import sys\n\nif __name__ == "__main__":\n    sys.exit(0)\n'
NO_IMPORTS = '"""A module of constants."""\n\nROOT = "/"\n'
NOTHING_AT_ALL = '"""A module that says nothing."""\n'
FORWARDER = "class C:\n    def f(self, x):\n        return self._other.f(x)\n"
AWAIT_FORWARDER = (
    "class C:\n    async def f(self, x):\n        return await self._other.f(x)\n"
)
DOCSTRING_FORWARDER = (
    "class C:\n"
    "    def f(self, x):\n"
    '        """Hand it on."""\n'
    "        return self._other.f(x)\n"
)
KEYWORD_FORWARDER = "class C:\n    def f(self, x):\n        return self._other.f(x=x)\n"
REORDERED = "class C:\n    def f(self, x, y):\n        return self._other.f(y, x)\n"
DOES_MORE = (
    "class C:\n"
    "    def f(self, x):\n"
    "        self._log(x)\n"
    "        return self._other.f(x)\n"
)
PLAIN_RETURN = "class C:\n    def f(self, x):\n        return x + 1\n"

#: The source script's shipped roots, and its rule-2 reach.
INCLUDE = ("hooks/**/*.py", "scripts/**/*.py")
FORWARDERS = ("**",)

POLICY_FILE = "pyproject.toml"
REEXPORT_MSG = "imports and defines nothing — a re-export module is not a split"
FORWARDS_MSG = "returns a call on its own arguments — move the callers, not the method"
MODULE_EXEMPT = "[tool.filepawl.barrels.module_exempt] {!r}: {}"
FORWARDER_EXEMPT = "[tool.filepawl.barrels.forwarder_exempt] {!r}: {}"
NO_FILE = "names no file"
DEFINES = "the module defines something, so it needs no exemption"
NO_MATCH = "matches no forwarder"

BARREL = "hooks/barrel.py"
GOOD = "hooks/good.py"
UNTOUCHED = "hooks/untouched.py"
FORWARDING = "hooks/forwarding.py"


def _run(
    files: dict[str, str | int],
    repo: RepoFactory,
    *,
    names: list[str] | None = None,
    exempt: Mapping[str, str] = MappingProxyType({}),
    module_exempt: Mapping[str, str] = MappingProxyType({}),
) -> list[Finding]:
    root = repo(files)
    barrels = BarrelsPolicy(
        include=INCLUDE,
        forwarders=FORWARDERS,
        module_exempt=dict(module_exempt),
        forwarder_exempt=dict(exempt),
    )
    policy: Policy = dataclasses.replace(default_policy(), barrels=barrels)
    return BarrelsGate().run(build_tree(root, policy, names), policy, State())


def test_reexport_module_fails_and_is_named(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one re-export run.

    "a module of imports and nothing else fails" and "the re-export module is
    named on stdout".
    """
    assert _run({BARREL: REEXPORT}, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_module_defining_a_function_passes(repo: RepoFactory) -> None:
    """Port of "a module defining a function passes"."""
    files: dict[str, str | int] = {GOOD: DEFINES_FUNCTION, BARREL: REEXPORT}
    assert _run(files, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_module_defining_a_constant_passes(repo: RepoFactory) -> None:
    """Port of "a module defining a constant passes"."""
    files: dict[str, str | int] = {GOOD: DEFINES_CONSTANT, BARREL: REEXPORT}
    assert _run(files, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_all_alone_is_not_defining_something(repo: RepoFactory) -> None:
    """Port of "__all__ alone does not count as defining something"."""
    assert _run({BARREL: ONLY_ALL}, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_body_under_main_guard_fails(repo: RepoFactory) -> None:
    """Port of "a module whose whole body sits under the main guard fails"."""
    assert _run({BARREL: ONLY_MAIN_GUARD}, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_module_importing_nothing_is_not_a_reexport(repo: RepoFactory) -> None:
    """Port of "a module that imports nothing is not a re-export"."""
    files: dict[str, str | int] = {GOOD: NO_IMPORTS, BARREL: REEXPORT}
    assert _run(files, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_docstring_only_module_passes(repo: RepoFactory) -> None:
    """Port of "a module of nothing but a docstring passes"."""
    files: dict[str, str | int] = {GOOD: NOTHING_AT_ALL, BARREL: REEXPORT}
    assert _run(files, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_init_reexporting_package_surface_passes(repo: RepoFactory) -> None:
    """Port of "__init__.py re-exporting a package surface passes"."""
    files: dict[str, str | int] = {
        "scripts/pair/__init__.py": REEXPORT,
        BARREL: REEXPORT,
    }
    assert _run(files, repo) == [Finding(BARREL, REEXPORT_MSG)]


def test_forwarder_fails_and_is_named_with_its_function(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one forwarder run.

    "a method returning a call on its own arguments fails" and "the forwarder
    is named with its function on stdout".
    """
    assert _run({GOOD: FORWARDER}, repo) == [Finding(f"{GOOD}::f", FORWARDS_MSG)]


def test_awaited_pass_through_is_a_forwarder(repo: RepoFactory) -> None:
    """Port of "an awaited pass-through is a forwarder too"."""
    assert _run({GOOD: AWAIT_FORWARDER}, repo) == [Finding(f"{GOOD}::f", FORWARDS_MSG)]


def test_docstring_does_not_save_a_forwarder(repo: RepoFactory) -> None:
    """Port of "a docstring does not save a forwarder"."""
    assert _run({GOOD: DOCSTRING_FORWARDER}, repo) == [
        Finding(f"{GOOD}::f", FORWARDS_MSG)
    ]


def test_keyword_pass_through_is_knowingly_not_caught(repo: RepoFactory) -> None:
    """Port of "a keyword-argument pass-through is knowingly not caught"."""
    files: dict[str, str | int] = {GOOD: KEYWORD_FORWARDER, FORWARDING: FORWARDER}
    assert _run(files, repo) == [Finding(f"{FORWARDING}::f", FORWARDS_MSG)]


def test_reordered_arguments_are_not_a_forwarder(repo: RepoFactory) -> None:
    """Port of "a method reordering its arguments is not a forwarder"."""
    files: dict[str, str | int] = {GOOD: REORDERED, FORWARDING: FORWARDER}
    assert _run(files, repo) == [Finding(f"{FORWARDING}::f", FORWARDS_MSG)]


def test_method_doing_more_passes(repo: RepoFactory) -> None:
    """Port of "a method doing more than returning the call passes"."""
    files: dict[str, str | int] = {GOOD: DOES_MORE, FORWARDING: FORWARDER}
    assert _run(files, repo) == [Finding(f"{FORWARDING}::f", FORWARDS_MSG)]


def test_method_returning_its_own_expression_passes(repo: RepoFactory) -> None:
    """Port of "a method returning an expression of its own passes"."""
    files: dict[str, str | int] = {GOOD: PLAIN_RETURN, FORWARDING: FORWARDER}
    assert _run(files, repo) == [Finding(f"{FORWARDING}::f", FORWARDS_MSG)]


def test_exempt_forwarder_passes(repo: RepoFactory) -> None:
    """Port of "an exempt forwarder passes"."""
    exempt = {f"{GOOD}::f": "reaches the private collaborator"}
    files: dict[str, str | int] = {GOOD: FORWARDER, FORWARDING: FORWARDER}
    assert _run(files, repo, exempt=exempt) == [
        Finding(f"{FORWARDING}::f", FORWARDS_MSG)
    ]


def test_exempt_reexport_module_passes(repo: RepoFactory) -> None:
    """Port of "an exempt re-export module passes"."""
    module_exempt = {BARREL: "the surface is the point"}
    files: dict[str, str | int] = {BARREL: REEXPORT, UNTOUCHED: REEXPORT}
    assert _run(files, repo, module_exempt=module_exempt) == [
        Finding(UNTOUCHED, REEXPORT_MSG)
    ]


def test_forwarder_exemption_naming_no_file_is_stale(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one stale forwarder-exemption run.

    "a forwarder exemption naming no file fails as stale" and "the stale
    forwarder entry is named on stdout".
    """
    exempt = {"hooks/gone.py::f": "stale"}
    assert _run({GOOD: DEFINES_FUNCTION}, repo, exempt=exempt) == [
        Finding(POLICY_FILE, FORWARDER_EXEMPT.format("hooks/gone.py::f", NO_FILE))
    ]


def test_forwarder_exemption_matching_no_forwarder_is_stale(
    repo: RepoFactory,
) -> None:
    """Port of "a forwarder exemption matching no forwarder fails as stale"."""
    exempt = {f"{GOOD}::f": "stale"}
    assert _run({GOOD: DEFINES_FUNCTION}, repo, exempt=exempt) == [
        Finding(POLICY_FILE, FORWARDER_EXEMPT.format(f"{GOOD}::f", NO_MATCH))
    ]


def test_module_exemption_naming_no_file_is_stale(repo: RepoFactory) -> None:
    """Port of the self-test's rules for one stale module-exemption run.

    "a module exemption naming no file fails as stale" and "the stale module
    entry is named on stdout".
    """
    module_exempt = {"hooks/gone.py": "stale"}
    assert _run({GOOD: DEFINES_FUNCTION}, repo, module_exempt=module_exempt) == [
        Finding(POLICY_FILE, MODULE_EXEMPT.format("hooks/gone.py", NO_FILE))
    ]


def test_module_exemption_for_defining_module_is_stale(repo: RepoFactory) -> None:
    """Port of the self-test's rule for an exempted defining module.

    "a module exemption for a module that defines something fails as stale".
    """
    module_exempt = {GOOD: "stale"}
    assert _run({GOOD: DEFINES_FUNCTION}, repo, module_exempt=module_exempt) == [
        Finding(POLICY_FILE, MODULE_EXEMPT.format(GOOD, DEFINES))
    ]


def test_live_module_exemption_outside_the_named_set_passes(
    repo: RepoFactory,
) -> None:
    """Port of "a live module exemption for a file not on argv passes"."""
    files: dict[str, str | int] = {
        UNTOUCHED: REEXPORT,
        GOOD: DEFINES_FUNCTION,
        BARREL: REEXPORT,
    }
    module_exempt = {UNTOUCHED: "live"}
    assert _run(files, repo, names=[GOOD], module_exempt=module_exempt) == [
        Finding(BARREL, REEXPORT_MSG)
    ]


def test_stale_module_exemption_outside_the_named_set_fails(
    repo: RepoFactory,
) -> None:
    """Port of "a stale module exemption for a file not on argv still fails"."""
    files: dict[str, str | int] = {UNTOUCHED: DEFINES_FUNCTION, GOOD: DEFINES_FUNCTION}
    module_exempt = {UNTOUCHED: "stale"}
    assert _run(files, repo, names=[GOOD], module_exempt=module_exempt) == [
        Finding(POLICY_FILE, MODULE_EXEMPT.format(UNTOUCHED, DEFINES))
    ]


def test_live_forwarder_exemption_outside_the_named_set_passes(
    repo: RepoFactory,
) -> None:
    """Port of "a live forwarder exemption for a file not on argv passes"."""
    files: dict[str, str | int] = {
        UNTOUCHED: FORWARDER,
        GOOD: DEFINES_FUNCTION,
        FORWARDING: FORWARDER,
    }
    exempt = {f"{UNTOUCHED}::f": "live"}
    assert _run(files, repo, names=[GOOD], exempt=exempt) == [
        Finding(f"{FORWARDING}::f", FORWARDS_MSG)
    ]


def test_every_offender_is_reported_and_no_compliant_file(
    repo: RepoFactory,
) -> None:
    """Port of the self-test's rules for one mixed-tree run.

    "one offender among compliant files fails the gate", "every offender is
    reported, not only the first" and "a compliant file beside an offender is
    not named".
    """
    files: dict[str, str | int] = {
        "hooks/one.py": DEFINES_FUNCTION,
        "hooks/two.py": REEXPORT,
        "hooks/three.py": FORWARDER,
    }
    assert _run(files, repo, names=list(files)) == [
        Finding("hooks/three.py::f", FORWARDS_MSG),
        Finding("hooks/two.py", REEXPORT_MSG),
    ]
