"""Tests for filepawl.config: the policy loader (design.md §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from filepawl.config import (
    DEFAULT_POLICY_STUB,
    BarrelsPolicy,
    DircountPolicy,
    LanguagePolicy,
    LengthPolicy,
    NestingPolicy,
    Policy,
    default_policy,
    load_policy,
)
from filepawl.errors import ConfigError


def write(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


class TestBarrelsPolicy:
    def test_defaults(self) -> None:
        assert default_policy().barrels == BarrelsPolicy(
            include=("**/*.py",),
            forwarders=("**",),
            module_exempt={},
            forwarder_exempt={},
            enabled=True,
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.barrels]\n"
            'include = ["pkg/**/*.py"]\n'
            'forwarders = ["pkg/core/**"]\n'
            "enabled = false\n"
            "[tool.filepawl.barrels.module_exempt]\n"
            '"pkg/shim.py" = "entry point name"\n'
            "[tool.filepawl.barrels.forwarder_exempt]\n"
            '"pkg/core/a.py::f" = "facade"\n',
        )
        policy = load_policy(tmp_path)
        assert policy.barrels == BarrelsPolicy(
            include=("pkg/**/*.py",),
            forwarders=("pkg/core/**",),
            module_exempt={"pkg/shim.py": "entry point name"},
            forwarder_exempt={"pkg/core/a.py::f": "facade"},
            enabled=False,
        )
        assert "barrels" not in policy.gate_tables

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.barrels]\nscope = []\n")
        with pytest.raises(ConfigError, match="unknown key 'scope'"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.barrels.forwarder_exempt]\n" '"a.py::f" = 1\n',
        )
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)


class TestNestingPolicy:
    def test_defaults(self) -> None:
        assert default_policy().nesting == NestingPolicy(
            include=("**/*.py",), max_depth=4, exempt={}, enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.nesting]\n"
            'include = ["pkg/**/*.py"]\n'
            "max_depth = 3\n"
            "enabled = false\n"
            "[tool.filepawl.nesting.exempt]\n"
            '"pkg/a.py::C.f" = "parser state machine"\n',
        )
        policy = load_policy(tmp_path)
        assert policy.nesting == NestingPolicy(
            include=("pkg/**/*.py",),
            max_depth=3,
            exempt={"pkg/a.py::C.f": "parser state machine"},
            enabled=False,
        )
        assert "nesting" not in policy.gate_tables

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.nesting]\nmax = 4\n")
        with pytest.raises(ConfigError, match="unknown key 'max'"):
            load_policy(tmp_path)

    def test_max_depth_must_be_an_integer(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.nesting]\nmax_depth = "4"\n')
        with pytest.raises(ConfigError, match="max_depth must be an integer"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.nesting.exempt]\n"a.py::f" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_nesting_block(self) -> None:
        assert "# [tool.filepawl.nesting]" in DEFAULT_POLICY_STUB
        assert "# max_depth = 4" in DEFAULT_POLICY_STUB


class TestDefaultPolicy:
    def test_default_policy_matches_spec(self) -> None:
        policy = default_policy()
        assert policy == Policy(
            languages={"python": LanguagePolicy(include=("**/*.py",), mover="rope")},
            tests=("tests/**",),
            length=LengthPolicy(cap=500, cap_tests=800, watch=400),
            dircount=DircountPolicy(cap=15, cap_tests=30, exclude=("__init__.py",)),
            exempt={},
            gate_tables={},
        )

    def test_absent_pyproject_yields_default_policy(self, tmp_path: Path) -> None:
        assert load_policy(tmp_path) == default_policy()

    def test_pyproject_without_tool_filepawl_yields_default_policy(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, '[project]\nname = "x"\n')
        assert load_policy(tmp_path) == default_policy()

    def test_pyproject_without_tool_table_yields_default_policy(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, "x = 1\n")
        assert load_policy(tmp_path) == default_policy()


class TestParsing:
    def test_overrides_length_and_dircount(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            cap = 600
            cap_tests = 900
            watch = 450

            [tool.filepawl.dircount]
            cap = 20
            cap_tests = 40
            exclude = ["__init__.py", "__main__.py"]
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.length == LengthPolicy(cap=600, cap_tests=900, watch=450)
        assert policy.dircount == DircountPolicy(
            cap=20, cap_tests=40, exclude=("__init__.py", "__main__.py")
        )
        assert policy.languages == default_policy().languages

    def test_exempt_table(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.exempt]
            "scripts/fixture.py" = "provenance kept whole"
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.exempt == {"scripts/fixture.py": "provenance kept whole"}

    def test_tests_globs(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            tests = ["spec/**", "tests/**"]
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.tests == ("spec/**", "tests/**")

    def test_python_block_overrides_builtin_default(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py", "**/*.pyi"]
            mover = "command"
            mover_command = "true"
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.languages == {
            "python": LanguagePolicy(
                include=("**/*.py", "**/*.pyi"),
                mover="command",
                mover_command="true",
            )
        }

    def test_python_block_partial_override_keeps_other_builtin_fields(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py"]
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.languages["python"].mover == "rope"

    def test_free_form_language_block(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            languages = ["python", "javascript"]

            [tool.filepawl.javascript]
            include = ["**/*.js", "**/*.css"]
            mover = "command"
            mover_command = "npx jscodeshift -t scripts/move.js src/"
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.languages["javascript"] == LanguagePolicy(
            include=("**/*.js", "**/*.css"),
            mover="command",
            mover_command="npx jscodeshift -t scripts/move.js src/",
        )
        assert policy.languages["python"] == default_policy().languages["python"]

    def test_language_with_no_mover_is_none(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            languages = ["python", "ruby"]

            [tool.filepawl.ruby]
            include = ["**/*.rb"]
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.languages["ruby"] == LanguagePolicy(
            include=("**/*.rb",), mover=None, mover_command=None
        )

    def test_gate_tables_keeps_unknown_third_party_tables(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.docstrings]
            enabled = true
            min_coverage = 80
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.gate_tables == {
            "docstrings": {"enabled": True, "min_coverage": 80}
        }

    def test_gate_tables_excludes_reserved_and_language_tables(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            cap = 500

            [tool.filepawl.dircount]
            cap = 15

            [tool.filepawl.exempt]

            [tool.filepawl.python]
            include = ["**/*.py"]

            [tool.filepawl.thirdparty]
            enabled = true
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.gate_tables == {"thirdparty": {"enabled": True}}


class TestErrors:
    def test_unparseable_toml_raises_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "this is not [ valid toml")
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_unknown_top_level_key_raises_config_error(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            bogus = true
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_unknown_key_in_length_table_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            cap = 500
            bogus = 1
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_wrong_type_for_cap_raises_config_error(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            cap = "five hundred"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_bool_rejected_for_int_field(self, tmp_path: Path) -> None:
        # bool is a subclass of int in Python; it must still be rejected.
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            cap = true
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_wrong_type_for_exempt_reason_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.exempt]
            "scripts/fixture.py" = 1
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_language_listed_without_table_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            languages = ["ruby"]
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_language_table_missing_include_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            languages = ["ruby"]

            [tool.filepawl.ruby]
            mover = "command"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_language_table_unknown_key_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py"]
            bogus = 1
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_mover_wrong_type_raises_config_error(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py"]
            mover = 1
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_mover_unrecognized_string_name_is_accepted_here(
        self, tmp_path: Path
    ) -> None:
        # config.py defers "is this mover name registered" to the mover
        # registry; it only rejects non-string mover values.
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py"]
            mover = "some-future-plugin-mover"
            """,
        )
        policy = load_policy(tmp_path)
        assert policy.languages["python"].mover == "some-future-plugin-mover"

    def test_include_wrong_type_raises_config_error(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = "**/*.py"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_include_with_non_string_item_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.python]
            include = ["**/*.py", 1]
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_languages_wrong_type_raises_config_error(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl]
            languages = "python"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_filepawl_table_wrong_type_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, "[tool]\nfilepawl = 1\n")
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_dircount_exclude_wrong_type_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.dircount]
            exclude = "not-a-list"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)

    def test_dircount_enabled_wrong_type_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.dircount]
            enabled = "yes"
            """,
        )
        with pytest.raises(ConfigError):
            load_policy(tmp_path)


class TestEnabledFlag:
    def test_length_enabled_defaults_true(self) -> None:
        assert default_policy().length.enabled is True

    def test_length_enabled_can_be_disabled(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.length]
            enabled = false
            """,
        )
        assert load_policy(tmp_path).length.enabled is False

    def test_dircount_enabled_can_be_disabled(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.dircount]
            enabled = false
            """,
        )
        assert load_policy(tmp_path).dircount.enabled is False


class TestDefaultPolicyStub:
    def test_stub_is_all_commented(self) -> None:
        lines = DEFAULT_POLICY_STUB.splitlines()
        assert lines[0] == ""
        assert lines[1] == "# filepawl policy; uncomment to override defaults"
        for line in lines[2:]:
            assert line.startswith("#")

    def test_stub_contains_the_section_4_block(self) -> None:
        assert "[tool.filepawl]" in DEFAULT_POLICY_STUB
        assert "[tool.filepawl.python]" in DEFAULT_POLICY_STUB
        assert "cap = 500" in DEFAULT_POLICY_STUB
