"""Tests for filepawl.config_suite: the test-suite gates' policy (design.md §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from filepawl.config import default_policy, load_policy
from filepawl.config_suite import ClocksPolicy, SuiteGatePolicy
from filepawl.errors import ConfigError
from filepawl.policy_stub import DEFAULT_POLICY_STUB

#: Gates whose table holds only `include`, `exempt` and `enabled`.
PLAIN_GATES = ["absence", "existence", "claims", "private", "mocks"]


def write(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("gate", PLAIN_GATES)
def test_plain_gate_defaults_check_every_python_file(gate: str) -> None:
    assert getattr(default_policy().suite, gate) == SuiteGatePolicy(
        include=("**/*.py",), exempt={}, enabled=True
    )


@pytest.mark.parametrize("gate", PLAIN_GATES)
def test_plain_gate_table_is_read(gate: str, tmp_path: Path) -> None:
    write(
        tmp_path,
        f"[tool.filepawl.{gate}]\n"
        'include = ["tests/unit/**/*.py"]\n'
        "enabled = false\n"
        f"[tool.filepawl.{gate}.exempt]\n"
        '"tests/test_a.py::test_quiet" = "the contract"\n',
    )
    policy = load_policy(tmp_path)
    assert (getattr(policy.suite, gate), gate in policy.gate_tables) == (
        SuiteGatePolicy(
            include=("tests/unit/**/*.py",),
            exempt={"tests/test_a.py::test_quiet": "the contract"},
            enabled=False,
        ),
        False,
    )


@pytest.mark.parametrize("gate", PLAIN_GATES)
def test_plain_gate_unknown_key_is_config_error(gate: str, tmp_path: Path) -> None:
    write(tmp_path, f"[tool.filepawl.{gate}]\nallow_none = true\n")
    with pytest.raises(ConfigError, match="unknown key 'allow_none'"):
        load_policy(tmp_path)


@pytest.mark.parametrize("gate", PLAIN_GATES)
def test_plain_gate_exemption_reason_must_be_a_string(
    gate: str, tmp_path: Path
) -> None:
    write(tmp_path, f'[tool.filepawl.{gate}.exempt]\n"a.py::test_f" = 1\n')
    with pytest.raises(ConfigError, match="must be a string reason"):
        load_policy(tmp_path)


@pytest.mark.parametrize("gate", PLAIN_GATES)
def test_stub_carries_the_gate_and_exempt_blocks(gate: str) -> None:
    blocks = (f"# [tool.filepawl.{gate}]\n", f"# [tool.filepawl.{gate}.exempt]\n")
    assert [block in DEFAULT_POLICY_STUB for block in blocks] == [True, True]


def test_clocks_defaults_read_the_three_pacing_names() -> None:
    assert default_policy().suite.clocks == ClocksPolicy(
        include=("**/*.py",),
        exempt={},
        enabled=True,
        names=("timeout", "interval", "delay"),
    )


def test_clocks_table_is_read_with_its_names(tmp_path: Path) -> None:
    write(
        tmp_path,
        "[tool.filepawl.clocks]\n"
        'include = ["tests/unit/**/*.py"]\n'
        'names = ["timeout", "alarm_threshold"]\n'
        "enabled = false\n"
        "[tool.filepawl.clocks.exempt]\n"
        '"tests/test_a.py::test_wait" = "the contract"\n',
    )
    assert load_policy(tmp_path).suite.clocks == ClocksPolicy(
        include=("tests/unit/**/*.py",),
        exempt={"tests/test_a.py::test_wait": "the contract"},
        enabled=False,
        names=("timeout", "alarm_threshold"),
    )


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ("names = [1]\n", "names must be a list of strings"),
        ("allow_sleep = true\n", "unknown key 'allow_sleep'"),
    ],
)
def test_clocks_bad_table_is_config_error(
    tmp_path: Path, table: str, message: str
) -> None:
    write(tmp_path, "[tool.filepawl.clocks]\n" + table)
    with pytest.raises(ConfigError, match=message):
        load_policy(tmp_path)


def test_stub_carries_the_clocks_names() -> None:
    blocks = (
        "# [tool.filepawl.clocks]\n",
        '# names = ["timeout", "interval", "delay"]\n',
        "# [tool.filepawl.clocks.exempt]\n",
    )
    assert [block in DEFAULT_POLICY_STUB for block in blocks] == [True, True, True]
