"""Tests for filepawl.config_suite: the test-suite gates' policy (design.md §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from filepawl.config import default_policy, load_policy
from filepawl.config_suite import AbsencePolicy
from filepawl.errors import ConfigError
from filepawl.policy_stub import DEFAULT_POLICY_STUB


def write(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


class TestAbsencePolicy:
    def test_defaults(self) -> None:
        assert default_policy().suite.absence == AbsencePolicy(
            include=("**/*.py",), exempt={}, enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.absence]\n"
            'include = ["tests/unit/**/*.py"]\n'
            "enabled = false\n"
            "[tool.filepawl.absence.exempt]\n"
            '"tests/test_a.py::test_quiet" = "silence is the contract"\n',
        )
        policy = load_policy(tmp_path)
        assert policy.suite.absence == AbsencePolicy(
            include=("tests/unit/**/*.py",),
            exempt={"tests/test_a.py::test_quiet": "silence is the contract"},
            enabled=False,
        )
        assert "absence" not in policy.gate_tables

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.absence]\nallow_none = true\n")
        with pytest.raises(ConfigError, match="unknown key 'allow_none'"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.absence.exempt]\n"a.py::test_f" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_absence_block(self) -> None:
        assert "# [tool.filepawl.absence]" in DEFAULT_POLICY_STUB
        assert "# [tool.filepawl.absence.exempt]" in DEFAULT_POLICY_STUB
