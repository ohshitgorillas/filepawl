"""Policy tables of the test-suite gates (design.md §4, §6.12)."""

from __future__ import annotations

from dataclasses import dataclass, field

from filepawl.config_values import bool_value, check_keys, exempt_table, str_list
from filepawl.errors import ConfigError

_ABSENCE_KEYS = ("include", "exempt", "enabled")


@dataclass(frozen=True)
class AbsencePolicy:
    include: tuple[str, ...] = ("**/*.py",)
    exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class SuitePolicies:
    """One policy per test-suite gate, keyed by the gate's table name."""

    absence: AbsencePolicy = field(default_factory=AbsencePolicy)


SUITE_TABLES = ("absence",)


def build_suite(raw: dict[str, object]) -> SuitePolicies:
    return SuitePolicies(absence=_build_absence(raw.get("absence")))


def _build_absence(table: object) -> AbsencePolicy:
    if table is None:
        return AbsencePolicy()
    where = "[tool.filepawl.absence]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _ABSENCE_KEYS, where)
    return AbsencePolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        exempt=exempt_table(table.get("exempt"), "[tool.filepawl.absence.exempt]"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )
