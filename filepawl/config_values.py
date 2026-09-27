"""Value checks for [tool.filepawl] tables (design.md §4).

Each check takes a raw TOML value and the table path it came from, and
returns the typed value or raises ConfigError naming that path.
"""

from __future__ import annotations

from datetime import date, datetime, time

from filepawl.errors import ConfigError

# A value `tomllib` can produce, named whole so a table carries no unnamed shape.
TomlValue = (
    str
    | int
    | float
    | bool
    | datetime
    | date
    | time
    | list["TomlValue"]
    | dict[str, "TomlValue"]
)


def exempt_table(
    table: object, where: str = "[tool.filepawl.exempt]"
) -> dict[str, str]:
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    result: dict[str, str] = {}
    for key, value in table.items():
        if not isinstance(value, str):
            raise ConfigError(f"{where}.{key!r} must be a string reason")
        result[key] = value
    return result


def check_keys(table: dict[str, object], allowed: tuple[str, ...], where: str) -> None:
    for key in table:
        if key not in allowed:
            raise ConfigError(f"unknown key {key!r} in {where}")


def str_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def int_value(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where} must be an integer")
    return value


def positive_int(value: object, where: str) -> int:
    count = int_value(value, where)
    if count < 1:
        raise ConfigError(f"{where} must be a positive integer")
    return count


def str_value(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a string")
    return value


def bool_value(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where} must be a boolean")
    return value


def gate_tables(
    raw: dict[str, object], known: set[str]
) -> dict[str, dict[str, TomlValue]]:
    """Return the tables [tool.filepawl] keeps for third-party gates, by gate name."""
    tables: dict[str, dict[str, TomlValue]] = {}
    for key, value in raw.items():
        if key in known:
            continue
        if not isinstance(value, dict):
            raise ConfigError(f"unknown key {key!r} in [tool.filepawl]")
        tables[key] = value
    return tables
