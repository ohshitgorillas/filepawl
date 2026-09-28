"""Tests for filepawl.config: the policy loader (design.md §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from filepawl.config import (
    DircountPolicy,
    JudgePolicy,
    LanguagePolicy,
    LengthPolicy,
    Policy,
    default_policy,
    load_policy,
)
from filepawl.config_code import (
    BarrelsPolicy,
    HandlersPolicy,
    NamedResultsPolicy,
    NestingPolicy,
    ReachPolicy,
    ReturnsPolicy,
)
from filepawl.errors import ConfigError
from filepawl.policy_stub import DEFAULT_POLICY_STUB


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
        assert (policy.barrels, "barrels" not in policy.gate_tables) == (
            BarrelsPolicy(
                include=("pkg/**/*.py",),
                forwarders=("pkg/core/**",),
                module_exempt={"pkg/shim.py": "entry point name"},
                forwarder_exempt={"pkg/core/a.py::f": "facade"},
                enabled=False,
            ),
            True,
        )

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
        assert (policy.nesting, "nesting" not in policy.gate_tables) == (
            NestingPolicy(
                include=("pkg/**/*.py",),
                max_depth=3,
                exempt={"pkg/a.py::C.f": "parser state machine"},
                enabled=False,
            ),
            True,
        )

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
        assert (
            "# [tool.filepawl.nesting]" in DEFAULT_POLICY_STUB,
            "# max_depth = 4" in DEFAULT_POLICY_STUB,
        ) == (True, True)


class TestReturnsPolicy:
    def test_defaults(self) -> None:
        assert default_policy().returns == ReturnsPolicy(
            include=("**/*.py",), exempt={}, enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.returns]\n"
            'include = ["pkg/**/*.py"]\n'
            "enabled = false\n"
            "[tool.filepawl.returns.exempt]\n"
            '"pkg/a.py::C.f" = "wire format, two message kinds"\n',
        )
        policy = load_policy(tmp_path)
        assert (policy.returns, "returns" not in policy.gate_tables) == (
            ReturnsPolicy(
                include=("pkg/**/*.py",),
                exempt={"pkg/a.py::C.f": "wire format, two message kinds"},
                enabled=False,
            ),
            True,
        )

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.returns]\nmax_shapes = 2\n")
        with pytest.raises(ConfigError, match="unknown key 'max_shapes'"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.returns.exempt]\n"a.py::f" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_returns_block(self) -> None:
        assert (
            "# [tool.filepawl.returns]" in DEFAULT_POLICY_STUB,
            "# [tool.filepawl.returns.exempt]" in DEFAULT_POLICY_STUB,
        ) == (True, True)


class TestNamedResultsPolicy:
    def test_defaults(self) -> None:
        assert default_policy().named_results == NamedResultsPolicy(
            include=("**/*.py",), exclude=(), enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.named_results]\n"
            'include = ["pkg/**/*.py"]\n'
            'exclude = ["pkg/wire/**"]\n'
            "enabled = false\n",
        )
        policy = load_policy(tmp_path)
        assert (policy.named_results, "named_results" not in policy.gate_tables) == (
            NamedResultsPolicy(
                include=("pkg/**/*.py",), exclude=("pkg/wire/**",), enabled=False
            ),
            True,
        )

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.named_results]\nexempt = {"a.py::f" = "x"}\n')
        with pytest.raises(ConfigError, match="unknown key 'exempt'"):
            load_policy(tmp_path)

    def test_exclude_must_be_a_list_of_strings(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.named_results]\nexclude = "pkg/**"\n')
        with pytest.raises(ConfigError, match="must be a list of strings"):
            load_policy(tmp_path)

    def test_stub_carries_the_named_results_block(self) -> None:
        assert (
            "# [tool.filepawl.named_results]" in DEFAULT_POLICY_STUB,
            "# exclude = []" in DEFAULT_POLICY_STUB,
        ) == (True, True)


class TestHandlersPolicy:
    def test_defaults(self) -> None:
        assert default_policy().handlers == HandlersPolicy(
            include=("**/*.py",), exempt={}, enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.handlers]\n"
            'include = ["pkg/**/*.py"]\n'
            "enabled = false\n"
            "[tool.filepawl.handlers.exempt]\n"
            '"pkg/a.py::main" = "the CLI boundary turns errors into exit codes"\n',
        )
        policy = load_policy(tmp_path)
        assert (policy.handlers, "handlers" not in policy.gate_tables) == (
            HandlersPolicy(
                include=("pkg/**/*.py",),
                exempt={
                    "pkg/a.py::main": "the CLI boundary turns errors into exit codes"
                },
                enabled=False,
            ),
            True,
        )

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.handlers]\nallow_none = true\n")
        with pytest.raises(ConfigError, match="unknown key 'allow_none'"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.handlers.exempt]\n"a.py::f" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_handlers_block(self) -> None:
        assert (
            "# [tool.filepawl.handlers]" in DEFAULT_POLICY_STUB,
            "# [tool.filepawl.handlers.exempt]" in DEFAULT_POLICY_STUB,
        ) == (True, True)


class TestReachPolicy:
    def test_defaults(self) -> None:
        assert default_policy().reach == ReachPolicy(
            include=("**/*.py",), exempt={}, enabled=True
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.reach]\n"
            'include = ["pkg/**/*.py"]\n'
            "enabled = false\n"
            "[tool.filepawl.reach.exempt]\n"
            '"pkg/a.py::_twin" = "shared with its twin module"\n',
        )
        policy = load_policy(tmp_path)
        assert (policy.reach, "reach" not in policy.gate_tables) == (
            ReachPolicy(
                include=("pkg/**/*.py",),
                exempt={"pkg/a.py::_twin": "shared with its twin module"},
                enabled=False,
            ),
            True,
        )

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.reach]\nallow_none = true\n")
        with pytest.raises(ConfigError, match="unknown key 'allow_none'"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.reach.exempt]\n"a.py::_x" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_reach_block(self) -> None:
        assert (
            "# [tool.filepawl.reach]" in DEFAULT_POLICY_STUB,
            "# [tool.filepawl.reach.exempt]" in DEFAULT_POLICY_STUB,
        ) == (True, True)


class TestJudgePolicy:
    def test_defaults(self) -> None:
        assert default_policy().judge == JudgePolicy(
            enabled=False, model="claude-sonnet-5", batch=6, timeout=300, exempt={}
        )

    def test_table_is_read(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            "[tool.filepawl.judge]\n"
            "enabled = true\n"
            'model = "claude-opus-5"\n'
            "batch = 3\n"
            "timeout = 60\n"
            "[tool.filepawl.judge.exempt]\n"
            '"pkg/hook.py::run_hook" = "the spec requires the hook to stay silent"\n',
        )
        policy = load_policy(tmp_path)
        assert (policy.judge, "judge" not in policy.gate_tables) == (
            JudgePolicy(
                enabled=True,
                model="claude-opus-5",
                batch=3,
                timeout=60,
                exempt={
                    "pkg/hook.py::run_hook": "the spec requires the hook to stay silent"
                },
            ),
            True,
        )

    def test_unknown_key_is_config_error(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.judge]\nretries = 3\n")
        with pytest.raises(ConfigError, match="unknown key 'retries'"):
            load_policy(tmp_path)

    def test_model_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, "[tool.filepawl.judge]\nmodel = 5\n")
        with pytest.raises(ConfigError, match=r"judge\]\.model must be a string"):
            load_policy(tmp_path)

    @pytest.mark.parametrize("key", ["batch", "timeout"])
    def test_counts_must_be_positive_integers(self, tmp_path: Path, key: str) -> None:
        write(tmp_path, f"[tool.filepawl.judge]\n{key} = 0\n")
        with pytest.raises(ConfigError, match=f"{key} must be a positive integer"):
            load_policy(tmp_path)

    def test_exemption_reason_must_be_a_string(self, tmp_path: Path) -> None:
        write(tmp_path, '[tool.filepawl.judge.exempt]\n"a.py::f" = 1\n')
        with pytest.raises(ConfigError, match="must be a string reason"):
            load_policy(tmp_path)

    def test_stub_carries_the_judge_block(self) -> None:
        assert (
            "# [tool.filepawl.judge]" in DEFAULT_POLICY_STUB,
            '# model = "claude-sonnet-5"' in DEFAULT_POLICY_STUB,
            "# [tool.filepawl.judge.exempt]" in DEFAULT_POLICY_STUB,
        ) == (True, True, True)


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
        assert (policy.length, policy.dircount, policy.languages) == (
            LengthPolicy(cap=600, cap_tests=900, watch=450),
            DircountPolicy(
                cap=20, cap_tests=40, exclude=("__init__.py", "__main__.py")
            ),
            default_policy().languages,
        )

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
        assert (policy.languages["javascript"], policy.languages["python"]) == (
            LanguagePolicy(
                include=("**/*.js", "**/*.css"),
                mover="command",
                mover_command="npx jscodeshift -t scripts/move.js src/",
            ),
            default_policy().languages["python"],
        )

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
        policy = load_policy(tmp_path)
        assert (policy.length.enabled, policy.dircount.enabled) == (False, True)

    def test_dircount_enabled_can_be_disabled(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            """
            [tool.filepawl.dircount]
            enabled = false
            """,
        )
        policy = load_policy(tmp_path)
        assert (policy.dircount.enabled, policy.length.enabled) == (False, True)


class TestDefaultPolicyStub:
    def test_stub_is_all_commented(self) -> None:
        lines = DEFAULT_POLICY_STUB.splitlines()
        uncommented = [line for line in lines[2:] if not line.startswith("#")]
        assert (lines[0], lines[1], uncommented) == (
            "",
            "# filepawl policy; uncomment to override defaults",
            [],
        )

    def test_stub_contains_the_section_4_block(self) -> None:
        assert (
            "[tool.filepawl]" in DEFAULT_POLICY_STUB,
            "[tool.filepawl.python]" in DEFAULT_POLICY_STUB,
            "cap = 500" in DEFAULT_POLICY_STUB,
        ) == (True, True, True)
