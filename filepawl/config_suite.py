"""Policy tables of the test-suite gates (design.md §4, §6.12)."""

from __future__ import annotations

from dataclasses import dataclass, field

from filepawl.config_values import bool_value, check_keys, exempt_table, str_list
from filepawl.errors import ConfigError

_PLAIN_KEYS = ("include", "exempt", "enabled")


@dataclass(frozen=True)
class SuiteGatePolicy:
    """A test-suite gate's table: the files it checks and its exemptions."""

    include: tuple[str, ...] = ("**/*.py",)
    exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class SuitePolicies:
    """One policy per test-suite gate, keyed by the gate's table name."""

    absence: SuiteGatePolicy = field(default_factory=SuiteGatePolicy)
    private: SuiteGatePolicy = field(default_factory=SuiteGatePolicy)
    mocks: SuiteGatePolicy = field(default_factory=SuiteGatePolicy)


SUITE_TABLES = ("absence", "private", "mocks")


def build_suite(raw: dict[str, object]) -> SuitePolicies:
    return SuitePolicies(
        absence=_build_plain("absence", raw.get("absence")),
        private=_build_plain("private", raw.get("private")),
        mocks=_build_plain("mocks", raw.get("mocks")),
    )


def _build_plain(name: str, table: object) -> SuiteGatePolicy:
    if table is None:
        return SuiteGatePolicy()
    where = f"[tool.filepawl.{name}]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _PLAIN_KEYS, where)
    return SuiteGatePolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        exempt=exempt_table(table.get("exempt"), f"[tool.filepawl.{name}.exempt]"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )
