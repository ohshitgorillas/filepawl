"""Acceptance test: filepawl reproduces each consumer's `ALLOWANCE` table.

The policy each test builds is docs/design.md §10 step 2: HQPTuner adds a
`javascript` block and the `junkcal_fixture.py` exemption, Gauntlet adds
`**/*.sh` to the include set, Trivia Judge departs from the defaults not at
all. Caps, the watch line and the test-path rule are read out of each script
rather than restated, so a consumer that retunes one retunes this test.

Each checkout is read and never written: the tree is scanned with
`git ls-files`, and `accept` runs against an empty in-memory state.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from filepawl.config import LanguagePolicy, Policy, default_policy
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
