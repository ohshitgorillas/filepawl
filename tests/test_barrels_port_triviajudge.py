"""Port of Trivia Judge's barrel-gate tests to filepawl's barrels gate.

Source: ``~/dev/triviajudge/tests/gates/test_check_no_barrels.py``. Each test
cites the source test it ports; parametrized rows keep the source's rows in
the source's order. The source script checks rule 2 only under
``triviajudge/`` and ``scripts/``, which is expressed here as the
``forwarders`` scope of the policy.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import BarrelsPolicy, Policy, default_policy
from filepawl.gates.barrels import BarrelsGate
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

IMPORTS_ALONE = """
import os
from pathlib import Path
"""

CONSTANT = """
import os

NAME = 1
"""

ANNOTATED_CONSTANT = """
import os

NAME: int = 1
"""

MANIFEST_ONLY = """
import os

__all__ = ["os"]
"""

ANNOTATED_MANIFEST = """
import os

__all__: list[str] = ["os"]
"""

DEFINES_A_FUNCTION = """
import os

def f():
    return os
"""

NO_IMPORTS = """
NAME = 1
"""

FORWARDER = """
class Holder:
    def f(self, x):
        return self.other.f(x)
"""

DOCSTRING_FORWARDER = '''
class Holder:
    def f(self, x):
        """Hand the call on."""
        return self.other.f(x)
'''

ASYNC_FORWARDER = """
class Holder:
    async def f(self, x):
        return await self.other.f(x)
"""

MODULE_FORWARDER = """
def f(a, b):
    return holder.f(a, b)
"""

KEYWORD_CALL = """
class Holder:
    def f(self, x):
        return self.other.f(x, scope=x)
"""

STARRED_CALL = """
class Holder:
    def f(self, x):
        return self.other.f(*x)
"""

SUBSCRIPT_ROOT = """
class Holder:
    def f(self, x):
        return self.other[0].f(x)
"""

PLAIN_CALL = """
class Holder:
    def f(self, x):
        return helper(x)
"""

EXTRA_STATEMENT = """
class Holder:
    def f(self, x):
        x = x + 1
        return self.other.f(x)
"""

BARE_RETURN = """
class Holder:
    def f(self, x):
        return
"""

REORDERED_ARGS = """
class Holder:
    def f(self, x, y):
        return self.other.f(y, x)
"""

REASON = "the collaborator has no other route in"

#: The source script's rule-2 trees.
FORWARDER_SCOPE = ("triviajudge/**", "scripts/**")

#: A file that defines something, so a tree needing no module of its own
#: under test still has a commit.
FILLER = ("triviajudge/filler.py", "NAME = 1\n")

POLICY_FILE = "pyproject.toml"
REEXPORT = "imports and defines nothing — a re-export module is not a split"
FORWARDS = "returns a call on its own arguments — move the callers, not the method"
MODULE_NO_FILE = "[tool.filepawl.barrels.module_exempt] {!r}: names no file"
MODULE_DEFINES = (
    "[tool.filepawl.barrels.module_exempt] {!r}: "
    "the module defines something, so it needs no exemption"
)
FORWARDER_NO_FILE = "[tool.filepawl.barrels.forwarder_exempt] {!r}: names no file"
FORWARDER_NO_MATCH = (
    "[tool.filepawl.barrels.forwarder_exempt] {!r}: matches no forwarder"
)

BARREL = "triviajudge/barrel.py"
MOD = "triviajudge/mod.py"
MOD_F = "triviajudge/mod.py::f"
GONE = "triviajudge/gone.py"
GONE_F = "triviajudge/gone.py::f"
PLAIN_F = "triviajudge/plain.py::f"
MOD_MISSING = "triviajudge/mod.py::missing"


def _run(
    root: Path,
    *,
    forwarder_exempt: dict[str, str] | None = None,
    module_exempt: dict[str, str] | None = None,
) -> list[Finding]:
    barrels = BarrelsPolicy(
        forwarders=FORWARDER_SCOPE,
        module_exempt=module_exempt or {},
        forwarder_exempt=forwarder_exempt or {},
    )
    policy: Policy = dataclasses.replace(default_policy(), barrels=barrels)
    return BarrelsGate().run(build_tree(root, policy), policy, State())


# --- behavior 1: a file of imports alone is a re-export, unless it is __init__ ---


@pytest.mark.parametrize(
    ("name", "source", "problems"),
    [
        (BARREL, IMPORTS_ALONE, [Finding(BARREL, REEXPORT)]),
        ("triviajudge/__init__.py", IMPORTS_ALONE, []),
        (
            "triviajudge/manifest.py",
            MANIFEST_ONLY,
            [Finding("triviajudge/manifest.py", REEXPORT)],
        ),
        (
            "triviajudge/annotated_manifest.py",
            ANNOTATED_MANIFEST,
            [Finding("triviajudge/annotated_manifest.py", REEXPORT)],
        ),
        ("triviajudge/constants.py", CONSTANT, []),
        ("triviajudge/annotated.py", ANNOTATED_CONSTANT, []),
        ("triviajudge/defines.py", DEFINES_A_FUNCTION, []),
        ("triviajudge/standalone.py", NO_IMPORTS, []),
    ],
)
def test_a_module_passes_only_while_it_defines_something_of_its_own(
    repo: RepoFactory, name: str, source: str, problems: list[Finding]
) -> None:
    """Port of `test_a_module_passes_only_while_it_defines_something_of_its_own`."""
    assert _run(repo({name: source})) == problems


# --- behavior 2: a function that returns a call on its own arguments forwards ---


@pytest.mark.parametrize(
    ("source", "problems"),
    [
        (FORWARDER, [Finding(MOD_F, FORWARDS)]),
        (DOCSTRING_FORWARDER, [Finding(MOD_F, FORWARDS)]),
        (ASYNC_FORWARDER, [Finding(MOD_F, FORWARDS)]),
        (MODULE_FORWARDER, [Finding(MOD_F, FORWARDS)]),
        (KEYWORD_CALL, []),
        (STARRED_CALL, []),
        (SUBSCRIPT_ROOT, []),
        (PLAIN_CALL, []),
        (EXTRA_STATEMENT, []),
        (BARE_RETURN, []),
        (REORDERED_ARGS, []),
    ],
)
def test_a_pass_through_fails_and_anything_that_does_more_passes(
    repo: RepoFactory, source: str, problems: list[Finding]
) -> None:
    """Port of `test_a_pass_through_fails_and_anything_that_does_more_passes`."""
    assert _run(repo({MOD: source})) == problems


@pytest.mark.parametrize(
    ("name", "problems"),
    [
        (MOD, [Finding(MOD_F, FORWARDS)]),
        ("scripts/gates/mod.py", [Finding("scripts/gates/mod.py::f", FORWARDS)]),
        ("elsewhere/mod.py", []),
    ],
)
def test_the_forwarder_rule_reaches_the_trees_it_names_and_no_others(
    repo: RepoFactory, name: str, problems: list[Finding]
) -> None:
    """Port of `test_the_forwarder_rule_reaches_the_trees_it_names_and_no_others`."""
    assert _run(repo({name: FORWARDER})) == problems


# --- behavior 3: an exemption silences its own site and nothing else ----------


@pytest.mark.parametrize(
    ("name", "source", "exempt", "module_exempt", "site"),
    [
        (BARREL, IMPORTS_ALONE, {}, {BARREL: REASON}, Finding(BARREL, REEXPORT)),
        (MOD, FORWARDER, {MOD_F: REASON}, {}, Finding(MOD_F, FORWARDS)),
    ],
)
def test_an_exempt_site_reports_nothing(
    repo: RepoFactory,
    name: str,
    source: str,
    exempt: dict[str, str],
    module_exempt: dict[str, str],
    site: Finding,
) -> None:
    """Port of `test_an_exempt_site_reports_nothing`.

    The same tree without the exemption reports the site, so the silence is
    the exemption's.
    """
    root = repo({name: source})
    plain = _run(root)
    exempted = _run(root, forwarder_exempt=exempt, module_exempt=module_exempt)
    assert (plain, exempted) == ([site], [])


# --- behavior 4: an exemption excusing nothing is itself a failure ------------


@pytest.mark.parametrize(
    ("existing", "source", "module_exempt", "problems"),
    [
        (BARREL, IMPORTS_ALONE, {BARREL: REASON}, []),
        (
            None,
            IMPORTS_ALONE,
            {GONE: REASON},
            [Finding(POLICY_FILE, MODULE_NO_FILE.format(GONE))],
        ),
        (
            "triviajudge/constants.py",
            CONSTANT,
            {"triviajudge/constants.py": REASON},
            [Finding(POLICY_FILE, MODULE_DEFINES.format("triviajudge/constants.py"))],
        ),
    ],
)
def test_a_module_exemption_stands_only_while_its_module_re_exports(
    repo: RepoFactory,
    existing: str | None,
    source: str,
    module_exempt: dict[str, str],
    problems: list[Finding],
) -> None:
    """Port of `test_a_module_exemption_stands_only_while_its_module_re_exports`.

    The source writes no file at all for the row naming a missing module; a
    git tree needs one commit, so that row carries a clean filler module.
    """
    files: dict[str, str | int] = dict([FILLER])
    if existing is not None:
        files = {existing: source}
    assert _run(repo(files), module_exempt=module_exempt) == problems


@pytest.mark.parametrize(
    ("existing", "source", "exempt", "problems"),
    [
        (MOD, FORWARDER, {MOD_F: REASON}, []),
        (
            None,
            FORWARDER,
            {GONE_F: REASON},
            [Finding(POLICY_FILE, FORWARDER_NO_FILE.format(GONE_F))],
        ),
        (
            MOD,
            FORWARDER,
            {MOD_MISSING: REASON},
            [
                Finding(POLICY_FILE, FORWARDER_NO_MATCH.format(MOD_MISSING)),
                Finding(MOD_F, FORWARDS),
            ],
        ),
        (
            "triviajudge/plain.py",
            PLAIN_CALL,
            {PLAIN_F: REASON},
            [Finding(POLICY_FILE, FORWARDER_NO_MATCH.format(PLAIN_F))],
        ),
    ],
)
def test_a_forwarder_exemption_stands_only_while_it_matches_a_forwarder(
    repo: RepoFactory,
    existing: str | None,
    source: str,
    exempt: dict[str, str],
    problems: list[Finding],
) -> None:
    """Port of `test_a_forwarder_exemption_stands_only_while_it_matches_a_forwarder`.

    The source calls the stale audit alone; the gate here runs whole, so the
    row whose exemption misses `mod.py::f` also reports that forwarder. The row
    naming a missing file carries a clean filler module so the tree can commit.
    """
    files: dict[str, str | int] = dict([FILLER])
    if existing is not None:
        files = {existing: source}
    assert _run(repo(files), forwarder_exempt=exempt) == problems


# --- behavior 5: every finding is reported --------------------------------------


def test_check_prints_every_finding_then_the_count_and_refuses(
    repo: RepoFactory,
) -> None:
    """Port of `test_check_prints_every_finding_then_the_count_and_refuses`.

    The findings are ported; the printed layout, count line and exit code
    belong to the source script's command line and are not.
    """
    root = repo({BARREL: IMPORTS_ALONE})
    assert _run(root, forwarder_exempt={GONE_F: REASON}) == [
        Finding(POLICY_FILE, FORWARDER_NO_FILE.format(GONE_F)),
        Finding(BARREL, REEXPORT),
    ]


def test_check_prints_nothing_when_every_file_is_clean(repo: RepoFactory) -> None:
    """Port of `test_check_prints_nothing_when_every_file_is_clean`.

    An exemption on the same clean module is reported stale, so the gate read
    the tree it stayed silent on.
    """
    root = repo({"triviajudge/constants.py": CONSTANT})
    clean = _run(root)
    audited = _run(root, module_exempt={"triviajudge/constants.py": REASON})
    stale = Finding(POLICY_FILE, MODULE_DEFINES.format("triviajudge/constants.py"))
    assert (clean, audited) == ([], [stale])
