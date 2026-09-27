"""Tests for filepawl.gates.suite.clocks: the clocks gate (design.md §6.20).

Every case of Trivia Judge's `tests/gates/test_test_clocks.py` and Gauntlet's
`test_clocks_selftest.py` has its counterpart here. Each passing shape sits one
line above a real sleep, so its verdict is the one finding naming that line.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import ClocksPolicy, SuitePolicies
from filepawl.gates import registry
from filepawl.gates.base import Finding
from filepawl.gates.suite.clocks import ClocksGate
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

PATH = "tests/test_c.py"
FIX = " — pace it through a clock the test advances"
OWN = {"pkg/__init__.py": ""}
HEAD = "import asyncio\nimport time\n"
SLEEP = "time.sleep(1)"


def _policy(**clocks: object) -> Policy:
    suite = SuitePolicies(clocks=ClocksPolicy(**clocks))  # type: ignore[arg-type]
    return dataclasses.replace(default_policy(), suite=suite)


def _gate(
    repo: RepoFactory,
    source: str,
    policy: Policy | None = None,
    path: str = PATH,
) -> list[Finding]:
    root = repo({**OWN, path: source})
    chosen = policy or _policy()
    return ClocksGate().run(build_tree(root, chosen), chosen, State())


def _body(*lines: str, head: str = HEAD) -> str:
    return (
        head
        + "def test_f(clock, poll, aw, flag):\n"
        + "".join(f"    {line}\n" for line in lines)
    )


def _line(head: str = HEAD) -> int:
    return head.count("\n") + 2


def _finding(lines: str, unit: str = "test_f", path: str = PATH) -> Finding:
    return Finding(f"{path}::{unit}", f"runs on the wall clock at {lines}{FIX}")


@pytest.mark.parametrize(
    ("head", "call"),
    [
        pytest.param("import time\n", "time.sleep(1)", id="time"),
        pytest.param("import time as t\n", "t.sleep(1)", id="time-alias"),
        pytest.param("from time import sleep\n", "sleep(1)", id="time-from"),
        pytest.param("import asyncio\n", "asyncio.sleep(0.25)", id="asyncio"),
        pytest.param("from asyncio import sleep as nap\n", "nap(0.25)", id="nap"),
        pytest.param("import trio\n", "trio.sleep(1)", id="trio"),
        pytest.param("import anyio\n", "anyio.sleep(1)", id="anyio"),
        pytest.param("import time\n", "time.sleep(GAP)", id="name"),
        pytest.param("import time\n", "time.sleep(clock.gap)", id="attribute"),
    ],
)
def test_real_sleep_fails_however_it_is_spelled(
    repo: RepoFactory, head: str, call: str
) -> None:
    assert _gate(repo, _body(call, head=head)) == [_finding(f"line {_line(head)}")]


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param("time.sleep(0)", id="zero-sleep"),
        pytest.param("time.sleep(0.0)", id="zero-float-sleep"),
        pytest.param("clock.sleep(5)", id="seam-sleep"),
        pytest.param("poll(clock=time.monotonic)", id="clock-named-not-called"),
        pytest.param("poll(timeout=5)", id="ceiling"),
        pytest.param("poll(timeout=0)", id="zero-timeout"),
        pytest.param("poll(read_timeout=0.5)", id="half-second"),
        pytest.param("poll(ratio=0.05)", id="other-name"),
        pytest.param("poll(retries=0.05)", id="other-name-suffix"),
        pytest.param("poll(alarm_threshold=0.05)", id="unlisted-name"),
        pytest.param("poll(interval=30.0 if flag else 60.0)", id="parked-branches"),
        pytest.param("poll({'timeout': 5})", id="ceiling-key"),
        pytest.param("poll({'ratio': 0.05})", id="other-key"),
        pytest.param("asyncio.wait_for(aw, 3.0)", id="wait-for-ceiling"),
        pytest.param("asyncio.timeout(5)", id="timeout-ceiling"),
    ],
)
def test_passing_shape_leaves_only_the_real_sleep_below_it(
    repo: RepoFactory, shape: str
) -> None:
    assert _gate(repo, _body(shape, SLEEP)) == [_finding(f"line {_line() + 1}")]


@pytest.mark.parametrize(
    ("head", "call"),
    [
        ("import time\n", "time.time()"),
        ("import time\n", "time.time_ns()"),
        ("import time\n", "time.monotonic()"),
        ("import time\n", "time.monotonic_ns()"),
        ("from time import perf_counter\n", "perf_counter()"),
        ("import time\n", "time.perf_counter_ns()"),
        ("from datetime import datetime\n", "datetime.now()"),
        ("from datetime import datetime\n", "datetime.utcnow()"),
        ("from datetime import datetime\n", "datetime.today()"),
        ("from datetime import date\n", "date.today()"),
        ("import datetime as dt\n", "dt.datetime.now(dt.UTC)"),
    ],
)
def test_real_clock_read_fails(repo: RepoFactory, head: str, call: str) -> None:
    assert _gate(repo, _body(call, head=head)) == [_finding(f"line {_line(head)}")]


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param("poll(timeout=0.05)", id="timeout"),
        pytest.param("poll(read_timeout=0.2)", id="suffixed-timeout"),
        pytest.param("poll(interval=0.05)", id="interval"),
        pytest.param("poll(poll_interval=0.02)", id="suffixed-interval"),
        pytest.param("poll(delay=0.1)", id="delay"),
        pytest.param("poll(retry_delay=1e-3)", id="suffixed-delay"),
        pytest.param("poll(poll_interval=0.02 if flag else 30.0)", id="body-branch"),
        pytest.param("poll(poll_interval=30.0 if flag else 0.02)", id="else-branch"),
        pytest.param("poll({'read_timeout': 0.05})", id="key"),
        pytest.param("poll({'interval': 0.01})", id="interval-key"),
        pytest.param("asyncio.wait_for(aw, 0.1)", id="wait-for"),
        pytest.param("asyncio.timeout(0.1)", id="asyncio-timeout"),
    ],
)
def test_small_duration_under_a_pacing_name_fails(
    repo: RepoFactory, shape: str
) -> None:
    assert _gate(repo, _body(shape)) == [_finding(f"line {_line()}")]


def test_name_added_to_names_is_read_as_pacing(repo: RepoFactory) -> None:
    policy = _policy(names=("timeout", "alarm_threshold"))
    source = _body("poll(alarm_threshold=0.05)", "poll(interval=0.05)")
    assert _gate(repo, source, policy) == [_finding(f"line {_line()}")]


def test_every_site_in_a_unit_is_listed_by_line(repo: RepoFactory) -> None:
    source = _body(SLEEP, "poll(timeout=0.05)", "time.monotonic()")
    lines = f"lines {_line()}, {_line() + 1}, {_line() + 2}"
    assert _gate(repo, source) == [_finding(lines)]


def test_module_level_clock_reports_under_module(repo: RepoFactory) -> None:
    source = HEAD + "START = time.monotonic()\n"
    assert _gate(repo, source) == [_finding("line 3", "<module>")]


def test_browser_test_gets_no_carve_out(repo: RepoFactory) -> None:
    path = "tests/e2e/test_browser.py"
    assert _gate(repo, _body(SLEEP), path=path) == [
        _finding(f"line {_line()}", path=path)
    ]


def _stale(key: str, message: str) -> Finding:
    return Finding(
        "pyproject.toml", f"[tool.filepawl.clocks.exempt] {key!r}: {message}"
    )


def test_exempt_unit_passes_and_others_still_fail(repo: RepoFactory) -> None:
    source = _body(SLEEP) + f"def test_g():\n    {SLEEP}\n"
    policy = _policy(exempt={f"{PATH}::test_f": "reason"})
    assert _gate(repo, source, policy) == [_finding(f"line {_line() + 2}", "test_g")]


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("tests/test_gone.py::test_f", "names no file"),
        ("pkg/__init__.py::f", "names no file"),
        (f"{PATH}::test_missing", "names no function"),
        (f"{PATH}::test_clean", "runs on no wall clock, so it needs no exemption"),
    ],
)
def test_stale_exemption_fails(repo: RepoFactory, key: str, message: str) -> None:
    source = _body(SLEEP) + "def test_clean(clock):\n    clock.sleep(5)\n"
    policy = _policy(exempt={key: "reason"})
    assert _gate(repo, source, policy) == [
        _stale(key, message),
        _finding(f"line {_line()}"),
    ]


def test_gate_is_discovered_unless_its_table_disables_it() -> None:
    on = registry.discover_gates(default_policy())
    off = registry.discover_gates(_policy(enabled=False))
    assert (
        [type(gate) for gate in on if gate.name == "clocks"],
        [gate.name for gate in off if gate.name == "clocks"],
    ) == ([ClocksGate], [])


def test_accept_leaves_state_unchanged(repo: RepoFactory) -> None:
    root = repo({**OWN, PATH: _body(SLEEP)})
    state = State()
    policy = _policy()
    assert ClocksGate().accept(build_tree(root, policy), policy, state) is state
