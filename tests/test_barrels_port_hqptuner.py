"""HQPTuner's no-barrels suite, ported onto filepawl's barrels gate.

Source: `~/dev/hqptuner/tests/gates/test_no_barrels.py`. Each test cites the
source test it ports. HQPTuner's `FORWARDER_SCOPE` prefixes become forwarder
globs; its `FORWARDER_EXEMPT` and `MODULE_EXEMPT` mappings become
`forwarder_exempt` and `module_exempt`. "Named on stdout" becomes a finding
whose path or message carries the name.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.config import BarrelsPolicy, Policy, default_policy
from filepawl.gates.barrels import BarrelsGate
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import build_tree

RepoFactory = Callable[[dict[str, "str | int"]], Path]

REEXPORT = "imports and defines nothing — a re-export module is not a split"
FORWARDS = "returns a call on its own arguments — move the callers, not the method"

HQPTUNER_SCOPE = (
    "hqptuner/core/**",
    "hqptuner/lanes/**",
    "hqptuner/presets/**",
    "hqptuner/engine/**",
    "hqptuner/conf/**",
)

FORWARDER = '''
class Tuner:
    """A thing that owns a client."""

    def set_volume(self, level, ramp):
        """Set the volume."""
        return self.client.set_volume(level, ramp)
'''

BARE_FORWARDER = """
class Tuner:
    def set_volume(self, level, ramp):
        return self.client.set_volume(level, ramp)
"""

ASYNC_FORWARDER = """
class Tuner:
    async def set_volume(self, level, ramp):
        return await self.client.set_volume(level, ramp)
"""

PARAMETER_ROOTED_FORWARDER = """
def set_volume(client, level, ramp):
    return client.set_volume(level, ramp)
"""

MODULE_ROOTED_FORWARDER = """
from hqptuner.presets import presetlane


class Presets:
    async def read_preset(self, name):
        return await presetlane.read(self, name)
"""

NON_FIRST_PARAMETER_ROOTED_FORWARDER = """
class Tuner:
    def f(self, client, x):
        return client.g(self, client, x)
"""

NON_FIRST_PARAMETER_ROOTED_DROPPED = """
class Tuner:
    def f(self, client, x):
        return client.g(self, x)
"""

ATTRIBUTE_DELEGATION = """
class Tuner:
    def value(self):
        return self.client.value
"""

IMPORTS_ALL_AND_A_CONSTANT = """
from hqptuner.core.tuner import Tuner

DEFAULT_RATE = 44100

__all__ = ["Tuner", "DEFAULT_RATE"]
"""

REORDERED = """
class Tuner:
    def set_volume(self, level, ramp):
        return self.client.set_volume(ramp, level)
"""

GUARDED = '''
class Tuner:
    def set_volume(self, level, ramp):
        """Set the volume."""
        level = max(level, 0)
        return self.client.set_volume(level, ramp)
'''

BARREL = """
from hqptuner.core.tuner import Tuner
from hqptuner.core.volume import ramp
"""

BARREL_WITH_ALL = """
from hqptuner.core.tuner import Tuner
from hqptuner.core.volume import ramp

__all__ = ["Tuner", "ramp"]
"""

IMPORTS_AND_CONSTANTS = """
import enum

DEFAULT_RATE = 44100
SUPPORTED_RATES = (44100, 48000, 96000)
RATE_KIND = enum.IntEnum("RATE_KIND", ["pcm", "sdm"])
"""

IMPORTS_AND_A_FUNCTION = """
import math


def area(r):
    return math.pi * r * r
"""

IMPORTS_AND_A_CLASS = """
import json


class Codec:
    def dumps(self, value):
        payload = dict(value)
        return json.dumps(payload, sort_keys=True)
"""

WHY = "the protocol interface requires this name"
PUBLIC = "the public import path third parties already use"


def _policy(
    forwarder_exempt: dict[str, str] | None = None,
    module_exempt: dict[str, str] | None = None,
) -> Policy:
    barrels = BarrelsPolicy(
        forwarders=HQPTUNER_SCOPE,
        forwarder_exempt=forwarder_exempt or {},
        module_exempt=module_exempt or {},
    )
    return dataclasses.replace(default_policy(), barrels=barrels)


def _run(root: Path, policy: Policy, paths: list[str] | None = None) -> list[Finding]:
    return BarrelsGate().run(build_tree(root, policy, paths), policy, State())


def _named(findings: list[Finding], needle: str) -> bool:
    return any(needle in f.path or needle in f.message for f in findings)


def _stale_module(path: str, message: str) -> Finding:
    where = f"[tool.filepawl.barrels.module_exempt] {path!r}"
    return Finding("pyproject.toml", f"{where}: {message}")


def _stale_forwarder(key: str, message: str) -> Finding:
    where = f"[tool.filepawl.barrels.forwarder_exempt] {key!r}"
    return Finding("pyproject.toml", f"{where}: {message}")


DEFINES = "the module defines something, so it needs no exemption"


# --- rule 1: re-export modules -------------------------------------------------


def test_module_defining_a_class_passes(repo: RepoFactory) -> None:
    """Port of test_a_module_defining_a_class_passes_however_many_imports_it_has."""
    root = repo({"hqptuner/core/codec.py": IMPORTS_AND_A_CLASS})
    assert _run(root, _policy()) == []


def test_module_defining_only_a_function_passes(repo: RepoFactory) -> None:
    """Port of test_a_module_defining_only_a_function_passes."""
    root = repo({"hqptuner/core/util.py": IMPORTS_AND_A_FUNCTION})
    assert _run(root, _policy()) == []


def test_module_of_imports_and_constants_passes(repo: RepoFactory) -> None:
    """Port of test_a_module_of_imports_and_constants_passes."""
    root = repo({"hqptuner/core/rates.py": IMPORTS_AND_CONSTANTS})
    assert _run(root, _policy()) == []


def test_module_of_imports_defining_nothing_fails(repo: RepoFactory) -> None:
    """Port of test_a_module_of_imports_defining_nothing_fails."""
    root = repo({"hqptuner/core/facade.py": BARREL})
    assert _run(root, _policy()) == [Finding("hqptuner/core/facade.py", REEXPORT)]


def test_module_of_imports_defining_nothing_is_named(repo: RepoFactory) -> None:
    """Port of test_a_module_of_imports_defining_nothing_is_named_on_stdout."""
    root = repo({"hqptuner/core/facade.py": BARREL})
    assert _named(_run(root, _policy()), "hqptuner/core/facade.py")


def test_module_of_imports_and_only_an_all_manifest_fails(repo: RepoFactory) -> None:
    """Port of test_a_module_of_imports_and_only_an_all_manifest_fails."""
    root = repo({"hqptuner/core/facade.py": BARREL_WITH_ALL})
    assert _run(root, _policy()) == [Finding("hqptuner/core/facade.py", REEXPORT)]


def test_module_of_imports_all_manifest_and_constant_passes(
    repo: RepoFactory,
) -> None:
    """Port of test_a_module_of_imports_an_all_manifest_and_a_constant_passes."""
    root = repo({"hqptuner/core/rates.py": IMPORTS_ALL_AND_A_CONSTANT})
    assert _run(root, _policy()) == []


def test_empty_module_with_no_imports_passes(repo: RepoFactory) -> None:
    """Port of test_an_empty_module_with_no_imports_passes."""
    root = repo({"hqptuner/core/placeholder.py": ""})
    assert _run(root, _policy()) == []


def test_barrel_rule_applies_under_the_api_layer(repo: RepoFactory) -> None:
    """Port of test_the_barrel_rule_applies_to_a_module_under_the_api_layer."""
    root = repo({"hqptuner/api/facade.py": BARREL})
    assert _run(root, _policy()) == [Finding("hqptuner/api/facade.py", REEXPORT)]


def test_package_init_of_pure_imports_passes(repo: RepoFactory) -> None:
    """Port of test_a_package_init_of_pure_imports_passes."""
    root = repo({"hqptuner/core/__init__.py": BARREL})
    assert _run(root, _policy()) == []


def test_package_init_of_imports_and_all_manifest_passes(repo: RepoFactory) -> None:
    """Port of test_a_package_init_of_imports_and_an_all_manifest_passes."""
    root = repo({"hqptuner/core/__init__.py": BARREL_WITH_ALL})
    assert _run(root, _policy()) == []


# --- rule 2: trivial forwarders ------------------------------------------------


def test_method_returning_call_on_self_with_own_parameters_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_method_returning_a_call_on_self_with_its_own_parameters_fails."""
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/core/tuner.py::set_volume", FORWARDS)
    ]


def test_forwarder_is_named(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_is_named_on_stdout."""
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    paths = [f.path for f in _run(root, _policy())]
    assert "hqptuner/core/tuner.py::set_volume" in paths


def test_forwarder_with_no_docstring_fails(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_with_no_docstring_fails."""
    root = repo({"hqptuner/core/tuner.py": BARE_FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/core/tuner.py::set_volume", FORWARDS)
    ]


def test_awaited_forwarder_fails(repo: RepoFactory) -> None:
    """Port of test_an_awaited_forwarder_fails."""
    root = repo({"hqptuner/lanes/tuner.py": ASYNC_FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/lanes/tuner.py::set_volume", FORWARDS)
    ]


def test_forwarder_rooted_at_own_parameter_fails(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_rooted_at_one_of_its_own_parameters_fails."""
    root = repo({"hqptuner/engine/volume.py": PARAMETER_ROOTED_FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/engine/volume.py::set_volume", FORWARDS)
    ]


def test_forwarder_rooted_at_imported_module_fails(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_rooted_at_an_imported_module_fails."""
    root = repo({"hqptuner/core/presets.py": MODULE_ROOTED_FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/core/presets.py::read_preset", FORWARDS)
    ]


def test_module_rooted_forwarder_is_named(repo: RepoFactory) -> None:
    """Port of test_a_module_rooted_forwarder_is_named_on_stdout."""
    root = repo({"hqptuner/core/presets.py": MODULE_ROOTED_FORWARDER})
    paths = [f.path for f in _run(root, _policy())]
    assert "hqptuner/core/presets.py::read_preset" in paths


def test_pass_through_reordering_parameters_passes(repo: RepoFactory) -> None:
    """Port of test_a_pass_through_whose_call_reorders_the_parameters_passes."""
    root = repo({"hqptuner/core/tuner.py": REORDERED})
    assert _run(root, _policy()) == []


def test_method_doing_anything_before_return_passes(repo: RepoFactory) -> None:
    """Port of test_a_method_doing_anything_before_the_return_passes."""
    root = repo({"hqptuner/core/tuner.py": GUARDED})
    assert _run(root, _policy()) == []


def test_forwarder_under_the_api_layer_passes(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_under_the_api_layer_passes."""
    root = repo({"hqptuner/api/routes.py": FORWARDER})
    assert _run(root, _policy()) == []


def test_forwarder_outside_scoped_layers_passes(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_outside_the_scoped_layers_passes."""
    root = repo({"scripts/probes/probe_volume.py": FORWARDER})
    assert _run(root, _policy()) == []


def test_forwarder_rooted_at_non_first_parameter_fails(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_rooted_at_a_parameter_that_is_not_the_first_one_fails."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": NON_FIRST_PARAMETER_ROOTED_FORWARDER})
    assert _run(root, _policy()) == [Finding("hqptuner/core/tuner.py::f", FORWARDS)]


def test_call_rooted_at_later_parameter_dropping_it_passes(
    repo: RepoFactory,
) -> None:
    """Port of test_a_call_rooted_at_a_later_parameter_that_drops_that_parameter_passes."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": NON_FIRST_PARAMETER_ROOTED_DROPPED})
    assert _run(root, _policy()) == []


def test_method_returning_attribute_not_call_passes(repo: RepoFactory) -> None:
    """Port of test_a_method_returning_an_attribute_rather_than_a_call_passes."""
    root = repo({"hqptuner/core/tuner.py": ATTRIBUTE_DELEGATION})
    assert _run(root, _policy()) == []


def test_forwarder_inside_package_init_under_scoped_layer_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_inside_a_package_init_under_a_scoped_layer_fails."""
    root = repo({"hqptuner/core/__init__.py": FORWARDER})
    assert _run(root, _policy()) == [
        Finding("hqptuner/core/__init__.py::set_volume", FORWARDS)
    ]


@pytest.mark.parametrize("layer", ["core", "lanes", "presets", "engine", "conf"])
def test_forwarder_rule_applies_in_every_scoped_layer(
    repo: RepoFactory, layer: str
) -> None:
    """Port of test_the_forwarder_rule_applies_in_every_scoped_layer."""
    root = repo({f"hqptuner/{layer}/tuner.py": FORWARDER})
    assert _run(root, _policy()) == [
        Finding(f"hqptuner/{layer}/tuner.py::set_volume", FORWARDS)
    ]


# --- forwarder_exempt ----------------------------------------------------------


def test_exempt_forwarder_passes(repo: RepoFactory) -> None:
    """Port of test_an_exempt_forwarder_passes."""
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    policy = _policy(forwarder_exempt={"hqptuner/core/tuner.py::set_volume": WHY})
    assert _run(root, policy) == []


def test_exempt_forwarder_is_not_named(repo: RepoFactory) -> None:
    """Port of test_an_exempt_forwarder_is_not_named_on_stdout."""
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    policy = _policy(forwarder_exempt={"hqptuner/core/tuner.py::set_volume": WHY})
    assert not _named(_run(root, policy), "set_volume")


def test_exemption_excuses_only_the_function_it_names(repo: RepoFactory) -> None:
    """Port of test_an_exemption_excuses_only_the_function_it_names."""
    source = '''
class Tuner:
    def set_volume(self, level, ramp):
        """Set the volume."""
        return self.client.set_volume(level, ramp)

    def set_balance(self, offset):
        """Set the balance."""
        return self.client.set_balance(offset)
'''
    root = repo({"hqptuner/core/tuner.py": source})
    policy = _policy(forwarder_exempt={"hqptuner/core/tuner.py::set_volume": WHY})
    assert _run(root, policy) == [
        Finding("hqptuner/core/tuner.py::set_balance", FORWARDS)
    ]


def test_forwarder_exemption_whose_file_is_missing_fails(repo: RepoFactory) -> None:
    """Port of test_a_forwarder_exemption_whose_file_is_not_on_disk_fails_as_stale."""
    root = repo({"hqptuner/core/tuner.py": GUARDED})
    key = "hqptuner/core/deleted.py::set_volume"
    policy = _policy(forwarder_exempt={key: "excused for a forgotten reason"})
    assert _run(root, policy) == [_stale_forwarder(key, "names no file")]


def test_forwarder_exemption_whose_file_is_missing_is_named(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_exemption_whose_file_is_not_on_disk_is_named_on_stdout."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": GUARDED})
    key = "hqptuner/core/deleted.py::set_volume"
    policy = _policy(forwarder_exempt={key: "excused for a forgotten reason"})
    assert _named(_run(root, policy), "hqptuner/core/deleted.py")


def test_forwarder_exemption_naming_no_such_forwarder_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_exemption_naming_no_such_forwarder_fails_as_stale."""
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    exempt = {
        "hqptuner/core/tuner.py::set_volume": WHY,
        "hqptuner/core/tuner.py::set_balance": "excused for a reason nobody remembers",
    }
    assert _run(root, _policy(forwarder_exempt=exempt)) == [
        _stale_forwarder("hqptuner/core/tuner.py::set_balance", "matches no forwarder")
    ]


def test_forwarder_exemption_naming_no_such_forwarder_is_named(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_exemption_naming_no_such_forwarder_is_named_on_stdout."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": FORWARDER})
    exempt = {
        "hqptuner/core/tuner.py::set_volume": WHY,
        "hqptuner/core/tuner.py::set_balance": "excused for a reason nobody remembers",
    }
    assert _named(_run(root, _policy(forwarder_exempt=exempt)), "set_balance")


def test_forwarder_exemption_on_function_that_stopped_forwarding_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_exemption_naming_a_function_that_stopped_forwarding_fails_as_stale."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": GUARDED})
    key = "hqptuner/core/tuner.py::set_volume"
    assert _run(root, _policy(forwarder_exempt={key: WHY})) == [
        _stale_forwarder(key, "matches no forwarder")
    ]


def test_forwarder_exemption_on_function_that_stopped_forwarding_is_named(
    repo: RepoFactory,
) -> None:
    """Port of test_a_forwarder_exemption_naming_a_function_that_stopped_forwarding_is_named_on_stdout."""  # noqa: E501
    root = repo({"hqptuner/core/tuner.py": GUARDED})
    key = "hqptuner/core/tuner.py::set_volume"
    findings = _run(root, _policy(forwarder_exempt={key: WHY}))
    assert _named(findings, key)


def test_stale_forwarder_exemption_for_file_not_on_argv_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_stale_forwarder_exemption_for_a_file_not_passed_on_argv_still_fails."""  # noqa: E501
    root = repo(
        {
            "hqptuner/core/untouched.py": GUARDED,
            "hqptuner/core/committed.py": IMPORTS_AND_A_CLASS,
        }
    )
    key = "hqptuner/core/untouched.py::set_volume"
    policy = _policy(forwarder_exempt={key: "excused long ago"})
    assert _run(root, policy, ["hqptuner/core/committed.py"]) == [
        _stale_forwarder(key, "matches no forwarder")
    ]


def test_live_forwarder_exemption_for_file_not_on_argv_passes(
    repo: RepoFactory,
) -> None:
    """Port of test_a_live_forwarder_exemption_for_a_file_not_passed_on_argv_passes."""
    root = repo(
        {
            "hqptuner/core/untouched.py": FORWARDER,
            "hqptuner/core/committed.py": IMPORTS_AND_A_CLASS,
        }
    )
    policy = _policy(forwarder_exempt={"hqptuner/core/untouched.py::set_volume": WHY})
    assert _run(root, policy, ["hqptuner/core/committed.py"]) == []


# --- module_exempt -------------------------------------------------------------


def test_exempt_re_export_module_passes(repo: RepoFactory) -> None:
    """Port of test_an_exempt_re_export_module_passes."""
    root = repo({"hqptuner/core/facade.py": BARREL})
    policy = _policy(module_exempt={"hqptuner/core/facade.py": PUBLIC})
    assert _run(root, policy) == []


def test_exempt_re_export_module_is_not_named(repo: RepoFactory) -> None:
    """Port of test_an_exempt_re_export_module_is_not_named_on_stdout."""
    root = repo({"hqptuner/core/facade.py": BARREL})
    policy = _policy(module_exempt={"hqptuner/core/facade.py": PUBLIC})
    assert not _named(_run(root, policy), "hqptuner/core/facade.py")


def test_module_exemption_whose_path_is_missing_fails(repo: RepoFactory) -> None:
    """Port of test_a_module_exemption_whose_path_is_not_on_disk_fails_as_stale."""
    root = repo({"hqptuner/core/codec.py": IMPORTS_AND_A_CLASS})
    path = "hqptuner/core/deleted.py"
    policy = _policy(module_exempt={path: "excused for a forgotten reason"})
    assert _run(root, policy) == [_stale_module(path, "names no file")]


def test_module_exemption_whose_path_is_missing_is_named(repo: RepoFactory) -> None:
    """Port of test_a_module_exemption_whose_path_is_not_on_disk_is_named_on_stdout."""
    root = repo({"hqptuner/core/codec.py": IMPORTS_AND_A_CLASS})
    path = "hqptuner/core/deleted.py"
    policy = _policy(module_exempt={path: "excused for a forgotten reason"})
    assert _named(_run(root, policy), path)


def test_module_exemption_on_module_that_defines_something_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_module_exemption_naming_a_module_that_defines_something_fails_as_stale."""  # noqa: E501
    root = repo({"hqptuner/core/codec.py": IMPORTS_AND_A_CLASS})
    path = "hqptuner/core/codec.py"
    policy = _policy(module_exempt={path: PUBLIC})
    assert _run(root, policy) == [_stale_module(path, DEFINES)]


def test_module_exemption_naming_a_package_init_fails(repo: RepoFactory) -> None:
    """Port of test_a_module_exemption_naming_a_package_init_fails_as_stale."""
    root = repo({"hqptuner/core/__init__.py": BARREL})
    path = "hqptuner/core/__init__.py"
    findings = _run(root, _policy(module_exempt={path: "the package surface"}))
    assert findings == [
        Finding(
            "pyproject.toml",
            f"[tool.filepawl.barrels.module_exempt] {path!r}: "
            "the module defines something, so it needs no exemption",
        )
    ]


def test_module_exemption_naming_a_package_init_is_named(repo: RepoFactory) -> None:
    """Port of test_a_module_exemption_naming_a_package_init_is_named_on_stdout."""
    root = repo({"hqptuner/core/__init__.py": BARREL})
    path = "hqptuner/core/__init__.py"
    findings = _run(root, _policy(module_exempt={path: "the package surface"}))
    assert _named(findings, path)


def test_stale_module_exemption_for_file_not_on_argv_fails(
    repo: RepoFactory,
) -> None:
    """Port of test_a_stale_module_exemption_for_a_file_not_passed_on_argv_still_fails."""  # noqa: E501
    root = repo(
        {
            "hqptuner/core/untouched.py": IMPORTS_AND_A_CLASS,
            "hqptuner/core/committed.py": IMPORTS_AND_A_FUNCTION,
        }
    )
    path = "hqptuner/core/untouched.py"
    policy = _policy(module_exempt={path: "excused long ago"})
    assert _run(root, policy, ["hqptuner/core/committed.py"]) == [
        _stale_module(path, DEFINES)
    ]


def test_live_module_exemption_for_file_not_on_argv_passes(
    repo: RepoFactory,
) -> None:
    """Port of test_a_live_module_exemption_for_a_file_not_passed_on_argv_passes."""
    root = repo(
        {
            "hqptuner/core/untouched.py": BARREL,
            "hqptuner/core/committed.py": IMPORTS_AND_A_FUNCTION,
        }
    )
    policy = _policy(module_exempt={"hqptuner/core/untouched.py": PUBLIC})
    assert _run(root, policy, ["hqptuner/core/committed.py"]) == []


# --- whole tree ----------------------------------------------------------------


def test_tree_with_neither_shape_passes(repo: RepoFactory) -> None:
    """Port of test_a_tree_with_neither_shape_passes."""
    root = repo(
        {
            "hqptuner/core/codec.py": IMPORTS_AND_A_CLASS,
            "hqptuner/core/guarded.py": GUARDED,
            "hqptuner/core/rates.py": IMPORTS_AND_CONSTANTS,
            "hqptuner/core/__init__.py": BARREL,
        }
    )
    assert _run(root, _policy()) == []
