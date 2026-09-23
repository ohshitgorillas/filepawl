"""Policy loader: reads [tool.filepawl] from pyproject.toml (design.md §4)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from filepawl.errors import ConfigError

# Names validated here belong to filepawl's own built-in movers. A name
# outside this tuple is not rejected by config.py: it is passed through as
# a string and validated later by the mover registry, which also knows
# about third-party entry-point movers config.py has no visibility into.
KNOWN_MOVERS = ("rope", "command")

_RESERVED_TABLES = ("length", "dircount", "exempt", "barrels", "nesting")
_TOP_LEVEL_SCALAR_KEYS = ("languages", "tests")
_LANGUAGE_KEYS = ("include", "mover", "mover_command")
_LENGTH_KEYS = ("cap", "cap_tests", "watch", "enabled")
_DIRCOUNT_KEYS = ("cap", "cap_tests", "exclude", "enabled")
_BARRELS_KEYS = (
    "include",
    "forwarders",
    "module_exempt",
    "forwarder_exempt",
    "enabled",
)
_NESTING_KEYS = ("include", "max_depth", "exempt", "enabled")


@dataclass(frozen=True)
class LanguagePolicy:
    include: tuple[str, ...]
    mover: str | None = None
    mover_command: str | None = None


@dataclass(frozen=True)
class LengthPolicy:
    cap: int = 500
    cap_tests: int = 800
    watch: int = 400
    enabled: bool = True


@dataclass(frozen=True)
class DircountPolicy:
    cap: int = 15
    cap_tests: int = 30
    exclude: tuple[str, ...] = ("__init__.py",)
    enabled: bool = True


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
class Policy:
    languages: dict[str, LanguagePolicy]
    tests: tuple[str, ...]
    length: LengthPolicy
    dircount: DircountPolicy
    exempt: dict[str, str]
    gate_tables: dict[str, dict[str, object]]
    barrels: BarrelsPolicy = field(default_factory=BarrelsPolicy)
    nesting: NestingPolicy = field(default_factory=NestingPolicy)


def default_policy() -> Policy:
    """The policy in force when pyproject.toml carries no [tool.filepawl]."""
    return Policy(
        languages={"python": _DEFAULT_PYTHON},
        tests=("tests/**",),
        length=LengthPolicy(),
        dircount=DircountPolicy(),
        exempt={},
        gate_tables={},
    )


_DEFAULT_PYTHON = LanguagePolicy(include=("**/*.py",), mover="rope")
_BUILTIN_LANGUAGE_DEFAULTS = {"python": _DEFAULT_PYTHON}


def load_policy(root: Path) -> Policy:
    path = root / "pyproject.toml"
    if not path.is_file():
        return default_policy()

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"unparseable pyproject.toml: {exc}") from exc

    tool = data.get("tool")
    if tool is None:
        return default_policy()
    if not isinstance(tool, dict):
        raise ConfigError("[tool] must be a table")

    raw = tool.get("filepawl")
    if raw is None:
        return default_policy()
    if not isinstance(raw, dict):
        raise ConfigError("[tool.filepawl] must be a table")

    return _build_policy(raw)


def _build_policy(raw: dict[str, object]) -> Policy:
    language_names = _str_list(raw.get("languages", ["python"]), "languages")
    test_globs = _str_list(raw.get("tests", ["tests/**"]), "tests")

    length = _build_length(raw.get("length"))
    dircount = _build_dircount(raw.get("dircount"))
    exempt = _build_exempt(raw.get("exempt"))
    barrels = _build_barrels(raw.get("barrels"))
    nesting = _build_nesting(raw.get("nesting"))

    languages = {name: _build_language(name, raw.get(name)) for name in language_names}

    known = set(_TOP_LEVEL_SCALAR_KEYS) | set(_RESERVED_TABLES) | set(language_names)
    gate_tables: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if key in known:
            continue
        if isinstance(value, dict):
            gate_tables[key] = value
        else:
            raise ConfigError(f"unknown key {key!r} in [tool.filepawl]")

    return Policy(
        languages=languages,
        tests=tuple(test_globs),
        length=length,
        dircount=dircount,
        exempt=exempt,
        gate_tables=gate_tables,
        barrels=barrels,
        nesting=nesting,
    )


def _build_language(name: str, table: object) -> LanguagePolicy:
    default = _BUILTIN_LANGUAGE_DEFAULTS.get(name)

    if table is None:
        if default is not None:
            return default
        raise ConfigError(
            f"{name!r} is listed under languages but [tool.filepawl.{name}] "
            "is missing"
        )

    if not isinstance(table, dict):
        raise ConfigError(f"[tool.filepawl.{name}] must be a table")

    for key in table:
        if key not in _LANGUAGE_KEYS:
            raise ConfigError(f"unknown key {key!r} in [tool.filepawl.{name}]")

    include_default = default.include if default is not None else None
    include_raw = table.get("include", include_default)
    if include_raw is None:
        raise ConfigError(f"[tool.filepawl.{name}] needs 'include'")
    include = _str_list(include_raw, f"[tool.filepawl.{name}].include")

    mover_default = default.mover if default is not None else None
    mover = table.get("mover", mover_default)
    if mover is not None and not isinstance(mover, str):
        raise ConfigError(f"[tool.filepawl.{name}].mover must be a string")

    mover_command_default = default.mover_command if default is not None else None
    mover_command = table.get("mover_command", mover_command_default)
    if mover_command is not None and not isinstance(mover_command, str):
        raise ConfigError(f"[tool.filepawl.{name}].mover_command must be a string")

    return LanguagePolicy(
        include=tuple(include), mover=mover, mover_command=mover_command
    )


def _build_length(table: object) -> LengthPolicy:
    if table is None:
        return LengthPolicy()
    if not isinstance(table, dict):
        raise ConfigError("[tool.filepawl.length] must be a table")
    _check_keys(table, _LENGTH_KEYS, "[tool.filepawl.length]")
    return LengthPolicy(
        cap=_int(table.get("cap", 500), "[tool.filepawl.length].cap"),
        cap_tests=_int(table.get("cap_tests", 800), "[tool.filepawl.length].cap_tests"),
        watch=_int(table.get("watch", 400), "[tool.filepawl.length].watch"),
        enabled=_bool(table.get("enabled", True), "[tool.filepawl.length].enabled"),
    )


def _build_dircount(table: object) -> DircountPolicy:
    if table is None:
        return DircountPolicy()
    if not isinstance(table, dict):
        raise ConfigError("[tool.filepawl.dircount] must be a table")
    _check_keys(table, _DIRCOUNT_KEYS, "[tool.filepawl.dircount]")
    exclude = _str_list(
        table.get("exclude", ["__init__.py"]), "[tool.filepawl.dircount].exclude"
    )
    return DircountPolicy(
        cap=_int(table.get("cap", 15), "[tool.filepawl.dircount].cap"),
        cap_tests=_int(
            table.get("cap_tests", 30), "[tool.filepawl.dircount].cap_tests"
        ),
        exclude=tuple(exclude),
        enabled=_bool(table.get("enabled", True), "[tool.filepawl.dircount].enabled"),
    )


def _build_barrels(table: object) -> BarrelsPolicy:
    if table is None:
        return BarrelsPolicy()
    where = "[tool.filepawl.barrels]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    _check_keys(table, _BARRELS_KEYS, where)
    return BarrelsPolicy(
        include=_str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        forwarders=_str_list(table.get("forwarders", ["**"]), f"{where}.forwarders"),
        module_exempt=_build_exempt(
            table.get("module_exempt"), "[tool.filepawl.barrels.module_exempt]"
        ),
        forwarder_exempt=_build_exempt(
            table.get("forwarder_exempt"), "[tool.filepawl.barrels.forwarder_exempt]"
        ),
        enabled=_bool(table.get("enabled", True), f"{where}.enabled"),
    )


def _build_nesting(table: object) -> NestingPolicy:
    if table is None:
        return NestingPolicy()
    where = "[tool.filepawl.nesting]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    _check_keys(table, _NESTING_KEYS, where)
    return NestingPolicy(
        include=_str_list(table.get("include", ["**/*.py"]), f"{where}.include"),
        max_depth=_int(table.get("max_depth", 4), f"{where}.max_depth"),
        exempt=_build_exempt(table.get("exempt"), "[tool.filepawl.nesting.exempt]"),
        enabled=_bool(table.get("enabled", True), f"{where}.enabled"),
    )


def _build_exempt(
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


def _check_keys(table: dict[str, object], allowed: tuple[str, ...], where: str) -> None:
    for key in table:
        if key not in allowed:
            raise ConfigError(f"unknown key {key!r} in {where}")


def _str_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where} must be an integer")
    return value


def _bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where} must be a boolean")
    return value


DEFAULT_POLICY_STUB = (
    "\n# filepawl policy; uncomment to override defaults\n"
    + "\n".join(
        "# " + line
        for line in [
            "[tool.filepawl]",
            'languages = ["python"]',
            'tests = ["tests/**"]',
            "",
            "[tool.filepawl.length]",
            "cap = 500",
            "cap_tests = 800",
            "watch = 400",
            "",
            "[tool.filepawl.dircount]",
            "cap = 15",
            "cap_tests = 30",
            'exclude = ["__init__.py"]',
            "",
            "[tool.filepawl.exempt]",
            "# path = reason. Human-edited. Exempts from the hard cap only; "
            "the file still",
            "# needs an allowance entry and may not grow.",
            '# "scripts/junkcal_fixture.py" = "junkcal fixture oracle, '
            'provenance kept whole"',
            "",
            "[tool.filepawl.barrels]",
            'include = ["**/*.py"]',
            'forwarders = ["**"]',
            "",
            "[tool.filepawl.barrels.module_exempt]",
            "# path = reason. Human-edited. A module that defines nothing on purpose.",
            "",
            "[tool.filepawl.barrels.forwarder_exempt]",
            '# "path::function" = reason. Human-edited. A forwarder that is the '
            "right shape.",
            "",
            "[tool.filepawl.nesting]",
            'include = ["**/*.py"]',
            "max_depth = 4",
            "",
            "[tool.filepawl.nesting.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "nests past the limit on purpose.",
            "",
            "[tool.filepawl.python]",
            'include = ["**/*.py"]',
            'mover = "rope"',
            "",
            "[tool.filepawl.javascript]",
            'include = ["**/*.js", "**/*.css"]',
            'mover = "command"',
            'mover_command = "npx jscodeshift -t scripts/move.js --old '
            '{old} --new {new} src/"',
        ]
    )
    + "\n"
)
