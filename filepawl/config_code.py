"""Policy tables of the code gates (design.md §4, §6.6 to §6.10)."""

from __future__ import annotations

from dataclasses import dataclass, field

from filepawl.config_values import (
    bool_value,
    check_keys,
    exempt_table,
    int_value,
    str_list,
)
from filepawl.errors import ConfigError

_BARRELS_KEYS = (
    "include",
    "forwarders",
    "module_exempt",
    "forwarder_exempt",
    "enabled",
)
_NESTING_KEYS = ("include", "max_depth", "exempt", "enabled")
_RETURNS_KEYS = ("include", "exempt", "enabled")
_NAMED_RESULTS_KEYS = ("include", "exclude", "enabled")
_HANDLERS_KEYS = ("include", "exempt", "enabled")


@dataclass(frozen=True)
class BarrelsPolicy:
    include: tuple[str, ...] = ("**/*.py",)
    forwarders: tuple[str, ...] = ("**",)
    module_exempt: dict[str, str] = field(default_factory=dict)
    forwarder_exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class NestingPolicy:
    include: tuple[str, ...] = ("**/*.py",)
    max_depth: int = 4
    exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class ReturnsPolicy:
    include: tuple[str, ...] = ("**/*.py",)
    exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class NamedResultsPolicy:
    include: tuple[str, ...] = ("**/*.py",)
    exclude: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class HandlersPolicy:
    include: tuple[str, ...] = ("**/*.py",)
    exempt: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def build_barrels(table: object) -> BarrelsPolicy:
    if table is None:
        return BarrelsPolicy()
    where = "[tool.filepawl.barrels]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _BARRELS_KEYS, where)
    return BarrelsPolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        forwarders=str_list(table.get("forwarders", ["**"]), f"{where}.forwarders"),
        module_exempt=exempt_table(
            table.get("module_exempt"), "[tool.filepawl.barrels.module_exempt]"
        ),
        forwarder_exempt=exempt_table(
            table.get("forwarder_exempt"), "[tool.filepawl.barrels.forwarder_exempt]"
        ),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )


def build_nesting(table: object) -> NestingPolicy:
    if table is None:
        return NestingPolicy()
    where = "[tool.filepawl.nesting]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _NESTING_KEYS, where)
    return NestingPolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        max_depth=int_value(table.get("max_depth", 4), f"{where}.max_depth"),
        exempt=exempt_table(table.get("exempt"), "[tool.filepawl.nesting.exempt]"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )


def build_returns(table: object) -> ReturnsPolicy:
    if table is None:
        return ReturnsPolicy()
    where = "[tool.filepawl.returns]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _RETURNS_KEYS, where)
    return ReturnsPolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        exempt=exempt_table(table.get("exempt"), "[tool.filepawl.returns.exempt]"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )


def build_named_results(table: object) -> NamedResultsPolicy:
    if table is None:
        return NamedResultsPolicy()
    where = "[tool.filepawl.named_results]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _NAMED_RESULTS_KEYS, where)
    return NamedResultsPolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        exclude=str_list(table.get("exclude", []), f"{where}.exclude"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )


def build_handlers(table: object) -> HandlersPolicy:
    if table is None:
        return HandlersPolicy()
    where = "[tool.filepawl.handlers]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    check_keys(table, _HANDLERS_KEYS, where)
    return HandlersPolicy(
        include=str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        exempt=exempt_table(table.get("exempt"), "[tool.filepawl.handlers.exempt]"),
        enabled=bool_value(table.get("enabled", True), f"{where}.enabled"),
    )
