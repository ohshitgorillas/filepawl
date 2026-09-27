"""Clocks gate: no test runs on the wall clock (design.md §6.20).

A test that sleeps on a real clock, reads one, or hands the code a deadline it
waits out tests how long the machine takes, not what the code concludes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.suite.common import Imports, SiteGate, units

#: Seconds below which a duration is a wait rather than a ceiling.
_SMALL = 0.5
_SLEEPS = frozenset({"time.sleep", "asyncio.sleep", "trio.sleep", "anyio.sleep"})
_READS = frozenset(
    {
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
    }
)
#: Calls that take a deadline positionally, and the index it sits at.
_POSITIONAL = {"asyncio.wait_for": 1, "asyncio.timeout": 0}
_CLOCK = "clock"


def _number(node: ast.expr) -> float | None:
    """Return a numeric constant's value, or None; a bool is not a number."""
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return None
    return node.value if isinstance(node.value, (int, float)) else None


def _small(node: ast.expr) -> bool:
    """Return whether an expression is a small duration: a constant above 0 and
    under half a second, or a conditional expression with such a branch."""
    if isinstance(node, ast.IfExp):
        return _small(node.body) or _small(node.orelse)
    value = _number(node)
    return value is not None and 0 < value < _SMALL


def _pacing(name: str | None, names: tuple[str, ...]) -> bool:
    """Return whether a keyword or key is a pacing name, bare or suffixed."""
    return name is not None and any(
        name == pace or name.endswith(f"_{pace}") for pace in names
    )


def _waits(node: ast.Call) -> bool:
    """Return whether a sleep waits: anything but a literal 0 first argument."""
    return not node.args or _number(node.args[0]) != 0


def _call_lines(node: ast.Call, imports: Imports, names: tuple[str, ...]) -> list[int]:
    dotted = imports.dotted(node.func)
    lines = []
    if (dotted in _SLEEPS and _waits(node)) or dotted in _READS:
        lines.append(node.lineno)
    index = _POSITIONAL.get(dotted or "")
    if index is not None and len(node.args) > index and _small(node.args[index]):
        lines.append(node.args[index].lineno)
    lines += [
        keyword.value.lineno
        for keyword in node.keywords
        if _pacing(keyword.arg, names) and _small(keyword.value)
    ]
    return lines


def _dict_lines(node: ast.Dict, names: tuple[str, ...]) -> list[int]:
    return [
        key.lineno
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and _pacing(key.value, names)
        and _small(value)
    ]


def _lines(node: ast.AST, imports: Imports, names: tuple[str, ...]) -> list[int]:
    if isinstance(node, ast.Call):
        return _call_lines(node, imports, names)
    if isinstance(node, ast.Dict):
        return _dict_lines(node, names)
    return []


@dataclass
class ClocksGate(SiteGate):
    """Refuses tests that sleep on, read, or wait out a real clock."""

    name: str = "clocks"
    fix: str = "pace it through a clock the test advances"
    clean: str = "runs on no wall clock, so it needs no exemption"

    def sites(
        self, module: ast.Module, imports: Imports, policy: Policy
    ) -> list[tuple[str, int, str]]:
        names = policy.suite.clocks.names
        return [
            (unit, line, _CLOCK)
            for unit, node in units(module)
            for line in _lines(node, imports, names)
        ]

    def describe(self, details: list[str]) -> str:
        return "runs on the wall clock"
