"""Tests for filepawl.gates.registry.discover_gates (design.md §6.5)."""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path

import pytest

from filepawl.config import Policy, default_policy
from filepawl.config_suite import SUITE_TABLES
from filepawl.errors import ConfigError
from filepawl.gates import registry

BUILTINS = [
    "length",
    "dircount",
    "barrels",
    "nesting",
    "returns",
    "named_results",
    "handlers",
    "absence",
    "private",
    "mocks",
]


def _disabled(name: str) -> Policy:
    policy = default_policy()
    if name in SUITE_TABLES:
        off = dataclasses.replace(getattr(policy.suite, name), enabled=False)
        return dataclasses.replace(
            policy, suite=dataclasses.replace(policy.suite, **{name: off})
        )
    off = dataclasses.replace(getattr(policy, name), enabled=False)
    return dataclasses.replace(policy, **{name: off})


def _names(policy: Policy) -> list[str]:
    return [gate.name for gate in registry.discover_gates(policy)]


@pytest.mark.parametrize("name", BUILTINS)
def test_builtin_gate_is_dropped_when_its_table_disables_it(name: str) -> None:
    assert (name in _names(default_policy()), name in _names(_disabled(name))) == (
        True,
        False,
    )


def test_default_policy_discovers_builtins_first_in_order() -> None:
    assert _names(default_policy())[: len(BUILTINS)] == BUILTINS


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, source: str
) -> None:
    """Install a real distribution whose `filepawl.gates` entry point is
    `<module>:make`, found through importlib.metadata."""
    dist_dir = tmp_path / "dist"
    _write(dist_dir / module / "__init__.py", source)
    info = dist_dir / f"{module}-0.1.dist-info"
    _write(info / "METADATA", f"Metadata-Version: 2.1\nName: {module}\nVersion: 0.1\n")
    _write(info / "entry_points.txt", f"[filepawl.gates]\n{module} = {module}:make\n")
    monkeypatch.syspath_prepend(str(dist_dir))
    importlib.invalidate_caches()


GATE_SOURCE = (
    "class FakeGate:\n"
    "    name = 'fake'\n"
    "    def run(self, tree, policy, state):\n"
    "        return []\n"
    "    def accept(self, tree, policy, state):\n"
    "        return state\n"
    "def make():\n"
    "    return FakeGate()\n"
)


def test_entry_point_gate_is_discovered_unless_its_table_disables_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(tmp_path, monkeypatch, "fpgate_real", GATE_SOURCE)
    off = dataclasses.replace(
        default_policy(), gate_tables={"fake": {"enabled": False}}
    )
    assert ("fake" in _names(default_policy()), "fake" in _names(off)) == (True, False)


def test_entry_point_load_failure_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(tmp_path, monkeypatch, "fpgate_broken", "import no_such_module\n")
    with pytest.raises(ConfigError, match="fpgate_broken"):
        registry.discover_gates(default_policy())


def test_entry_point_missing_gate_attrs_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "class NotAGate:\n    pass\ndef make():\n    return NotAGate()\n"
    _install(tmp_path, monkeypatch, "fpgate_incomplete", source)
    with pytest.raises(ConfigError, match="fpgate_incomplete"):
        registry.discover_gates(default_policy())
