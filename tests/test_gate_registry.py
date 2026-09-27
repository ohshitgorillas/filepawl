"""Tests for filepawl.gates.registry.discover_gates (design.md §6.5)."""

from __future__ import annotations

import dataclasses
import sys
import types
from pathlib import Path

import pytest

from filepawl.config import (
    NamedResultsPolicy,
    NestingPolicy,
    ReturnsPolicy,
    default_policy,
)
from filepawl.errors import ConfigError
from filepawl.gates import registry


class _StubGate:
    """A gate with a fixed name that lets registry ordering and enable logic
    be tested independent of the built-in gates."""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, tree: object, policy: object, state: object) -> list[object]:
        return []

    def accept(self, tree: object, policy: object, state: object) -> object:
        return state


def _install_fake_module(
    monkeypatch: pytest.MonkeyPatch, dotted_name: str, factory_name: str, gate_name: str
) -> None:
    module = types.ModuleType(dotted_name)
    setattr(module, factory_name, lambda: _StubGate(gate_name))
    monkeypatch.setitem(sys.modules, dotted_name, module)


def _patch_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, "fake_length_mod", "FakeLength", "length")
    _install_fake_module(monkeypatch, "fake_dircount_mod", "FakeDircount", "dircount")
    monkeypatch.setattr(
        registry,
        "_BUILTIN_GATES",
        (
            ("length", "fake_length_mod", "FakeLength"),
            ("dircount", "fake_dircount_mod", "FakeDircount"),
        ),
    )


def test_nesting_disabled_via_policy_nesting_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_module(monkeypatch, "fake_nesting_mod", "FakeNesting", "nesting")
    monkeypatch.setattr(
        registry, "_BUILTIN_GATES", (("nesting", "fake_nesting_mod", "FakeNesting"),)
    )
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    policy = dataclasses.replace(default_policy(), nesting=NestingPolicy(enabled=False))

    enabled = [g.name for g in registry.discover_gates(default_policy())]
    disabled = [g.name for g in registry.discover_gates(policy)]
    assert (enabled, disabled) == (["nesting"], [])


def test_returns_disabled_via_policy_returns_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_module(monkeypatch, "fake_returns_mod", "FakeReturns", "returns")
    monkeypatch.setattr(
        registry, "_BUILTIN_GATES", (("returns", "fake_returns_mod", "FakeReturns"),)
    )
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    policy = dataclasses.replace(default_policy(), returns=ReturnsPolicy(enabled=False))

    enabled = [g.name for g in registry.discover_gates(default_policy())]
    disabled = [g.name for g in registry.discover_gates(policy)]
    assert (enabled, disabled) == (["returns"], [])


def test_named_results_disabled_via_policy_named_results_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_module(monkeypatch, "fake_named_mod", "FakeNamed", "named_results")
    monkeypatch.setattr(
        registry,
        "_BUILTIN_GATES",
        (("named_results", "fake_named_mod", "FakeNamed"),),
    )
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    policy = dataclasses.replace(
        default_policy(), named_results=NamedResultsPolicy(enabled=False)
    )

    enabled = [g.name for g in registry.discover_gates(default_policy())]
    disabled = [g.name for g in registry.discover_gates(policy)]
    assert (enabled, disabled) == (["named_results"], [])


def test_handlers_disabled_via_policy_handlers_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_module(monkeypatch, "fake_handlers_mod", "FakeHandlers", "handlers")
    monkeypatch.setattr(
        registry,
        "_BUILTIN_GATES",
        (("handlers", "fake_handlers_mod", "FakeHandlers"),),
    )
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    handlers = dataclasses.replace(default_policy().handlers, enabled=False)
    policy = dataclasses.replace(default_policy(), handlers=handlers)

    enabled = [g.name for g in registry.discover_gates(default_policy())]
    disabled = [g.name for g in registry.discover_gates(policy)]
    assert (enabled, disabled) == (["handlers"], [])


def test_absence_disabled_via_policy_absence_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_module(monkeypatch, "fake_absence_mod", "FakeAbsence", "absence")
    monkeypatch.setattr(
        registry,
        "_BUILTIN_GATES",
        (("absence", "fake_absence_mod", "FakeAbsence"),),
    )
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    suite = default_policy().suite
    absence = dataclasses.replace(suite.absence, enabled=False)
    policy = dataclasses.replace(
        default_policy(), suite=dataclasses.replace(suite, absence=absence)
    )

    enabled = [g.name for g in registry.discover_gates(default_policy())]
    disabled = [g.name for g in registry.discover_gates(policy)]
    assert (enabled, disabled) == (["absence"], [])


class _FakeEntryPoint:
    def __init__(self, name: str, loader: object) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> object:
        return self._loader()


def test_builtins_come_first_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_builtins(monkeypatch)
    monkeypatch.setattr(registry, "entry_points", lambda group: [])

    gates = registry.discover_gates(default_policy())

    assert [g.name for g in gates] == ["length", "dircount"]


def test_length_disabled_via_policy_length_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_builtins(monkeypatch)
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    policy = default_policy()
    policy = policy.__class__(
        languages=policy.languages,
        tests=policy.tests,
        length=policy.length.__class__(
            cap=policy.length.cap,
            cap_tests=policy.length.cap_tests,
            watch=policy.length.watch,
            enabled=False,
        ),
        dircount=policy.dircount,
        exempt=policy.exempt,
        gate_tables=policy.gate_tables,
    )

    gates = registry.discover_gates(policy)

    assert [g.name for g in gates] == ["dircount"]


def test_dircount_disabled_via_policy_dircount_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_builtins(monkeypatch)
    monkeypatch.setattr(registry, "entry_points", lambda group: [])
    policy = default_policy()
    policy = policy.__class__(
        languages=policy.languages,
        tests=policy.tests,
        length=policy.length,
        dircount=policy.dircount.__class__(
            cap=policy.dircount.cap,
            cap_tests=policy.dircount.cap_tests,
            exclude=policy.dircount.exclude,
            enabled=False,
        ),
        exempt=policy.exempt,
        gate_tables=policy.gate_tables,
    )

    gates = registry.discover_gates(policy)

    assert [g.name for g in gates] == ["length"]


def test_entry_point_load_failure_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_BUILTIN_GATES", ())

    def _boom() -> object:
        raise ImportError("no such module")

    ep = _FakeEntryPoint("bad", _boom)
    monkeypatch.setattr(registry, "entry_points", lambda group: [ep])

    with pytest.raises(ConfigError, match="bad"):
        registry.discover_gates(default_policy())


def test_entry_point_missing_gate_attrs_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_BUILTIN_GATES", ())

    class _NotAGate:
        pass

    ep = _FakeEntryPoint("incomplete", lambda: _NotAGate())
    monkeypatch.setattr(registry, "entry_points", lambda group: [ep])

    with pytest.raises(ConfigError, match="incomplete"):
        registry.discover_gates(default_policy())


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_entry_point_discovered_from_real_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build a minimal, real installed distribution (a package plus a
    .dist-info with entry_points.txt) and prove filepawl finds its gate
    through importlib.metadata, not through a mocked entry_points()."""
    monkeypatch.setattr(registry, "_BUILTIN_GATES", ())

    dist_dir = tmp_path / "dist"
    _write(
        dist_dir / "fakegate" / "__init__.py",
        "class FakeGate:\n"
        "    name = 'fake'\n"
        "    def run(self, tree, policy, state):\n"
        "        return []\n"
        "    def accept(self, tree, policy, state):\n"
        "        return state\n",
    )
    _write(
        dist_dir / "fakegate-0.1.dist-info" / "METADATA",
        "Metadata-Version: 2.1\nName: fakegate\nVersion: 0.1\n",
    )
    _write(
        dist_dir / "fakegate-0.1.dist-info" / "entry_points.txt",
        "[filepawl.gates]\nfake = fakegate:FakeGate\n",
    )

    monkeypatch.syspath_prepend(str(dist_dir))
    import importlib as _importlib

    _importlib.invalidate_caches()

    gates = registry.discover_gates(default_policy())
    assert [g.name for g in gates] == ["fake"]

    policy = default_policy()
    policy = policy.__class__(
        languages=policy.languages,
        tests=policy.tests,
        length=policy.length,
        dircount=policy.dircount,
        exempt=policy.exempt,
        gate_tables={"fake": {"enabled": False}},
    )
    gates = registry.discover_gates(policy)
    assert gates == []


def test_default_policy_discovers_real_builtins_in_order() -> None:
    pytest.importorskip("filepawl.gates.length")
    pytest.importorskip("filepawl.gates.dircount")

    gates = registry.discover_gates(default_policy())

    names = [g.name for g in gates]
    assert names[:2] == ["length", "dircount"]
