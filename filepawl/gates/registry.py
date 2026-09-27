"""Gate discovery: built-ins plus third-party entry points (design.md §6.5)."""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from filepawl.config import Policy
from filepawl.config_suite import SUITE_TABLES
from filepawl.errors import ConfigError

if TYPE_CHECKING:
    from filepawl.gates.base import Gate

_ENTRY_POINT_GROUP = "filepawl.gates"

# (gate name, module to import lazily, class/factory name in that module).
# Built-ins load lazily so this module has no import-time dependency on
# gates/length.py or gates/dircount.py.
_BUILTIN_GATES: tuple[tuple[str, str, str], ...] = (
    ("length", "filepawl.gates.length", "LengthGate"),
    ("dircount", "filepawl.gates.dircount", "DircountGate"),
    ("barrels", "filepawl.gates.barrels", "BarrelsGate"),
    ("nesting", "filepawl.gates.nesting", "NestingGate"),
    ("returns", "filepawl.gates.returns", "ReturnsGate"),
    ("named_results", "filepawl.gates.named_results", "NamedResultsGate"),
    ("handlers", "filepawl.gates.handlers", "HandlersGate"),
    ("absence", "filepawl.gates.suite.absence", "AbsenceGate"),
    ("private", "filepawl.gates.suite.private", "PrivateGate"),
    ("mocks", "filepawl.gates.suite.mocks", "MocksGate"),
)

_GATE_ATTRS = ("name", "run", "accept")


def discover_gates(policy: Policy) -> list[Gate]:
    """Built-ins first (length, then dircount), then every `filepawl.gates`
    entry point. A gate whose name is disabled in policy is dropped."""
    gates: list[Gate] = []

    for name, module_path, factory_name in _BUILTIN_GATES:
        if not _is_enabled(name, policy):
            continue
        module = importlib.import_module(module_path)
        factory = getattr(module, factory_name)
        gates.append(factory())

    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            factory = ep.load()
            gate = factory()
        except Exception as exc:
            raise ConfigError(
                f"entry point {ep.name!r} in group {_ENTRY_POINT_GROUP!r} "
                f"failed to load: {exc}"
            ) from exc

        missing = [attr for attr in _GATE_ATTRS if not hasattr(gate, attr)]
        if missing:
            raise ConfigError(
                f"entry point {ep.name!r} in group {_ENTRY_POINT_GROUP!r} "
                f"is not a valid gate (missing {', '.join(missing)})"
            )

        if not _is_enabled(gate.name, policy):
            continue

        gates.append(gate)

    return gates


def _is_enabled(name: str, policy: Policy) -> bool:
    if name == "length":
        return policy.length.enabled
    if name == "dircount":
        return policy.dircount.enabled
    if name == "barrels":
        return policy.barrels.enabled
    if name == "nesting":
        return policy.nesting.enabled
    if name == "returns":
        return policy.returns.enabled
    if name == "named_results":
        return policy.named_results.enabled
    if name == "handlers":
        return policy.handlers.enabled
    if name in SUITE_TABLES:
        enabled: bool = getattr(policy.suite, name).enabled
        return enabled
    table = policy.gate_tables.get(name, {})
    return table.get("enabled", True) is not False
