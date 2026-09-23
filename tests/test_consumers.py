"""Acceptance test: filepawl reproduces each consumer's `ALLOWANCE` table.

The policy each test builds is docs/design.md §10 step 2: HQPTuner adds a
`javascript` block and the `junkcal_fixture.py` exemption, Gauntlet adds
`**/*.sh` to the include set, Trivia Judge departs from the defaults not at
all. Caps, the watch line and the test-path rule are read out of each script
rather than restated, so a consumer that retunes one retunes this test.

Each checkout is read and never written: the tree is scanned with
`git ls-files`, and `accept` runs against an empty in-memory state.

The barrels gate is held to each consumer's own `no-barrels` script: the
script runs over the file set its Makefile or gate runner hands it, and the
gate, given the §10 barrels policy, finds the same offenders and the same
stale exemptions.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from filepawl.config import BarrelsPolicy, LanguagePolicy, Policy, default_policy
from filepawl.gates.barrels import BarrelsGate
from filepawl.gates.length import LengthGate
from filepawl.state import State
from filepawl.tree import Tree, build_tree

pytestmark = pytest.mark.consumers

DEV = Path.home() / "dev"
HQPTUNER = DEV / "hqptuner"
TRIVIAJUDGE = DEV / "triviajudge"
GAUNTLET = DEV / "gauntlet"

SCRIPTS = {
    HQPTUNER: "scripts/gates/check_file_length.py",
    TRIVIAJUDGE: "scripts/gates/check_file_length.py",
    GAUNTLET: "scripts/gates/file-length.py",
}


def _script_ast(root: Path) -> ast.Module:
    """Parse the consumer's gate script, skipping the test when it is absent."""
    if not (root / ".git").exists():
        pytest.skip(f"consumer checkout absent: {root}")
    script = root / SCRIPTS[root]
    if not script.is_file():
        pytest.skip(f"consumer gate script absent: {script}")
    return ast.parse(script.read_text(encoding="utf-8"))


def _assigned(module: ast.Module, name: str) -> Any:
    """Evaluate the module-level assignment to `name` as a literal."""
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                assert node.value is not None
                return ast.literal_eval(node.value)
    raise AssertionError(f"no module-level assignment to {name!r}")


def _test_globs(module: ast.Module) -> tuple[str, ...]:
    """Read the test-path rule off `limit_for` as filepawl `tests` globs.

    All three scripts spell the rule `Path(name).parts[0] == "tests"`, so the
    string literals in the function body are the test directories.
    """
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "limit_for":
            body = list(node.body)
            if ast.get_docstring(node) is not None:
                body = body[1:]
            names = [
                sub.value
                for stmt in body
                for sub in ast.walk(stmt)
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
            ]
            assert names, "limit_for names no test directory"
            return tuple(f"{name}/**" for name in names)
    raise AssertionError("no limit_for in the gate script")


def _policy(
    module: ast.Module,
    *,
    python_include: tuple[str, ...] = ("**/*.py",),
    languages: dict[str, LanguagePolicy] | None = None,
    exempt: dict[str, str] | None = None,
) -> Policy:
    """Default policy retuned to the script's constants and the §10 departures."""
    base = default_policy()
    length = dataclasses.replace(
        base.length,
        cap=_assigned(module, "MAX_LINES"),
        cap_tests=_assigned(module, "MAX_LINES_TESTS"),
        watch=_assigned(module, "WATCH_LINE"),
    )
    blocks = {"python": LanguagePolicy(include=python_include, mover="rope")}
    blocks.update(languages or {})
    return dataclasses.replace(
        base,
        languages=blocks,
        tests=_test_globs(module),
        length=length,
        exempt=exempt or {},
    )


def _accepted(root: Path, policy: Policy) -> tuple[Tree, State]:
    """Scan the checkout read-only and run `accept` over an empty state."""
    tree = build_tree(root, policy)
    return tree, LengthGate().accept(tree, policy, State())


def _table(state: State) -> dict[str, int]:
    return {path: entry.lines for path, entry in state.allowance.items()}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "hqptuner excludes .claude/hooks/shell_shapes.py and "
        "hqptuner/static/store/schema.js from its gate via Makefile and "
        "pre-commit, not via ALLOWANCE; filepawl has no include-set "
        "exclusion by owner decision, so init adds two entries; resolved "
        "at migration"
    ),
)
def test_hqptuner_allowance_reproduced() -> None:
    module = _script_ast(HQPTUNER)
    policy = _policy(
        module,
        languages={
            "javascript": LanguagePolicy(include=("**/*.js", "**/*.css")),
        },
        exempt=_assigned(module, "CAP_EXEMPT"),
    )
    tree, state = _accepted(HQPTUNER, policy)
    assert _table(state) == _assigned(module, "ALLOWANCE")
    assert LengthGate().run(tree, policy, state) == []


def test_triviajudge_allowance_reproduced() -> None:
    module = _script_ast(TRIVIAJUDGE)
    policy = _policy(module)
    tree, state = _accepted(TRIVIAJUDGE, policy)
    assert _table(state) == _assigned(module, "ALLOWANCE")
    assert LengthGate().run(tree, policy, state) == []


def test_gauntlet_allowance_reproduced() -> None:
    module = _script_ast(GAUNTLET)
    policy = _policy(module, python_include=("**/*.py", "**/*.sh"))
    tree, state = _accepted(GAUNTLET, policy)
    assert _table(state) == _assigned(module, "ALLOWANCE")
    assert LengthGate().run(tree, policy, state) == []


BARREL_SCRIPTS = {
    HQPTUNER: "scripts/gates/check_no_barrels.py",
    TRIVIAJUDGE: "scripts/gates/code/check_no_barrels.py",
    GAUNTLET: "scripts/gates/code/no-barrels.py",
}

_STALE = re.compile(r"^(?:MODULE|FORWARDER)_EXEMPT\[(.+)\]: ")
_GATE_STALE = re.compile(r"^\[tool\.filepawl\.barrels\.\w+\] (.+): ")


def _barrel_script(root: Path) -> Path:
    """Locate the consumer's barrels script, skipping when it is absent."""
    if not (root / ".git").exists():
        pytest.skip(f"consumer checkout absent: {root}")
    script = root / BARREL_SCRIPTS[root]
    if not script.is_file():
        pytest.skip(f"consumer barrels script absent: {script}")
    return script


def _listed(root: Path, *pathspecs: str) -> list[str]:
    """The tracked files the consumer hands its script, as its wiring lists them."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", *pathspecs],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in listed.stdout.split("\0") if name]


def _split(lines: list[str], stale: re.Pattern[str]) -> tuple[set[str], set[str]]:
    """Separate offender lines from stale-exemption keys."""
    offenders: set[str] = set()
    keys: set[str] = set()
    for line in lines:
        match = stale.match(line)
        if match is not None:
            keys.add(match.group(1))
        else:
            offenders.add(line)
    return offenders, keys


def _script_says(root: Path, script: Path, files: list[str]) -> list[str]:
    """Run the consumer's script read-only; return its problem lines."""
    result = subprocess.run(
        [sys.executable, str(script), *files],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return [line for line in result.stdout.splitlines() if ": " in line]


def _gate_says(root: Path, barrels: BarrelsPolicy) -> list[str]:
    policy = dataclasses.replace(default_policy(), barrels=barrels)
    findings = BarrelsGate().run(build_tree(root, policy), policy, State())
    return [f"{finding.path}: {finding.message}" for finding in findings]


def _barrels_agree(root: Path, files: list[str], barrels: BarrelsPolicy) -> None:
    script = _barrel_script(root)
    old = _split(_script_says(root, script, files), _STALE)
    new = _split(
        [line.removeprefix("pyproject.toml: ") for line in _gate_says(root, barrels)],
        _GATE_STALE,
    )
    assert new == old


def test_hqptuner_barrels_reproduced() -> None:
    module = ast.parse(_barrel_script(HQPTUNER).read_text(encoding="utf-8"))
    scope = _assigned(module, "FORWARDER_SCOPE")
    barrels = BarrelsPolicy(
        include=("hqptuner/**/*.py", "scripts/**/*.py"),
        forwarders=tuple(f"{prefix}**" for prefix in scope),
        module_exempt=_assigned(module, "MODULE_EXEMPT"),
        forwarder_exempt=_assigned(module, "FORWARDER_EXEMPT"),
    )
    files = _listed(HQPTUNER, "hqptuner/*.py", "scripts/*.py")
    _barrels_agree(HQPTUNER, files, barrels)


def test_triviajudge_barrels_reproduced() -> None:
    module = ast.parse(_barrel_script(TRIVIAJUDGE).read_text(encoding="utf-8"))
    scope = _assigned(module, "FORWARDER_SCOPE")
    barrels = BarrelsPolicy(
        include=("triviajudge/**/*.py", "scripts/**/*.py"),
        forwarders=tuple(f"{prefix}**" for prefix in scope),
    )
    files = _listed(TRIVIAJUDGE, "triviajudge/*.py", "scripts/*.py")
    _barrels_agree(TRIVIAJUDGE, files, barrels)


def test_gauntlet_barrels_reproduced() -> None:
    barrels = BarrelsPolicy(include=("hooks/**/*.py", "scripts/**/*.py"))
    files = _listed(GAUNTLET, "hooks/*.py", "scripts/*.py")
    _barrels_agree(GAUNTLET, files, barrels)
