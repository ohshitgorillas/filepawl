"""Tests for `filepawl mv` and the mover backends (docs/design.md §8)."""

from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from filepawl.cli import main
from filepawl.errors import ConfigError
from filepawl.movers import registry
from filepawl.state import STATE_FILE

Repo = Callable[[dict[str, str | int]], Path]

PROJECT = '[project]\nname = "sample"\nversion = "0.0.0"\n'

# `[tool.filepawl.python]` inherits `mover = "rope"` from the built-in
# python defaults (config.py), so a block exercising the git fallback has
# to carry a different name.
PLAIN = "plain"


def policy(
    *,
    language: str = PLAIN,
    include: str = '["**/*.py"]',
    mover: str | None = None,
    mover_command: str | None = None,
) -> str:
    lines = [
        PROJECT,
        "[tool.filepawl]",
        f'languages = ["{language}"]',
        "",
        f"[tool.filepawl.{language}]",
        f"include = {include}",
    ]
    if mover is not None:
        lines.append(f'mover = "{mover}"')
    if mover_command is not None:
        lines.append(f'mover_command = "{mover_command}"')
    return "\n".join(lines) + "\n"


def tracked(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.split()


def allowance_of(root: Path) -> dict[str, object]:
    table = tomllib.loads((root / STATE_FILE).read_text(encoding="utf-8"))["allowance"]
    assert isinstance(table, dict)
    return table


# --- command backend ---------------------------------------------------


def test_command_backend_runs_the_template_and_records_its_argv(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(
                mover="command", mover_command="sh bin/move.sh {old} {new}"
            ),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    (root / "bin").mkdir()
    (root / "bin" / "move.sh").write_text(
        'printf "%s\\n" "$@" > "$(dirname "$0")/argv.log"\nmv "$1" "$2"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 0

    argv = (root / "bin" / "argv.log").read_text(encoding="utf-8").split()
    assert argv == ["pkg/a.py", "pkg/b.py"]
    assert not (root / "pkg" / "a.py").exists()
    assert (root / "pkg" / "b.py").read_text(encoding="utf-8") == "X = 1\n"
    assert capsys.readouterr().out.splitlines()[-1] == "0 stale references"


def test_command_backend_non_zero_exit_is_a_config_error(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(mover="command", mover_command="exit 3"),
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 2

    err = capsys.readouterr().err
    assert "exit 3" in err
    assert (root / "pkg" / "a.py").exists()


def test_command_backend_rejects_an_unknown_placeholder(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(
                mover="command", mover_command="sh bin/move.sh {other}"
            ),
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 2

    err = capsys.readouterr().err
    assert "sh bin/move.sh {other}" in err
    assert (root / "pkg" / "a.py").exists()


def test_command_backend_shell_quotes_the_paths(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old = "pkg/odd name $HOME.py"
    new = "pkg/still odd $x.py"
    root = repo(
        {
            "pyproject.toml": policy(
                mover="command", mover_command="sh bin/move.sh {old} {new}"
            ),
            "pkg/__init__.py": "",
            old: "X = 1\n",
        }
    )
    (root / "bin").mkdir()
    (root / "bin" / "move.sh").write_text(
        'printf "%s\\n" "$@" > "$(dirname "$0")/argv.log"\nmv "$1" "$2"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(root)

    assert main(["mv", old, new]) == 0

    argv = (root / "bin" / "argv.log").read_text(encoding="utf-8").splitlines()
    assert argv == [old, new]
    assert (root / new).read_text(encoding="utf-8") == "X = 1\n"
    assert not (root / old).exists()
    capsys.readouterr()


def test_command_backend_needs_mover_command(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"pyproject.toml": policy(mover="command"), "pkg/a.py": "X = 1\n"})
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 2
    assert "mover_command" in capsys.readouterr().err


# --- git fallback ------------------------------------------------------


def test_no_mover_falls_back_to_git_mv(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/sub/a.py"]) == 0

    assert "pkg/sub/a.py" in tracked(root)
    assert "pkg/a.py" not in tracked(root)
    assert capsys.readouterr().out.splitlines() == ["0 stale references"]


def test_git_mv_failure_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"pyproject.toml": policy(), "pkg/__init__.py": ""})
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/missing.py", "pkg/other.py"]) == 2
    assert "git mv" in capsys.readouterr().err


def test_git_mv_on_an_untracked_old_path_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo({"pyproject.toml": policy(), "pkg/__init__.py": ""})
    (root / "pkg" / "loose.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/loose.py", "pkg/moved.py"]) == 2

    assert "git mv" in capsys.readouterr().err
    assert (root / "pkg" / "loose.py").exists()
    assert not (root / "pkg" / "moved.py").exists()


def test_unmatched_old_path_exits_two(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(include='["**/*.js"]'),
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 2
    assert "no language block" in capsys.readouterr().err


# --- stale-reference grep ----------------------------------------------


def test_stale_refs_report_dotted_and_literal_hits_with_a_count(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(),
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/mod.py": "def fn() -> int:\n    return 1\n",
            "tests/test_x.py": (
                "import mock\n\n" 'with mock.patch("pkg.mod.fn"):\n' "    pass\n"
            ),
            "tools/paths.py": 'PATHS = ["pkg/mod.py"]\n',
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/mod.py", "pkg/sub/mod.py"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        'tests/test_x.py:3: with mock.patch("pkg.mod.fn"):',
        'tools/paths.py:1: PATHS = ["pkg/mod.py"]',
        "2 stale references",
    ]


# --- allowance state ---------------------------------------------------


def test_allowance_entry_moves_to_the_new_path(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    (root / STATE_FILE).write_text(
        "version = 1\n\n[allowance]\n"
        '"pkg/a.py" = { lines = 444, reason = "kept whole" }\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/sub/a.py"]) == 0

    assert allowance_of(root) == {
        "pkg/sub/a.py": {"lines": 444, "reason": "kept whole"}
    }
    capsys.readouterr()


def test_state_file_untouched_when_there_is_no_entry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 0

    assert not (root / STATE_FILE).exists()
    capsys.readouterr()


# --- rope backend ------------------------------------------------------


def test_rope_missing_prints_the_install_line(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(
        {
            "pyproject.toml": policy(mover="rope"),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)
    monkeypatch.setitem(sys.modules, "rope", None)

    assert main(["mv", "pkg/a.py", "pkg/sub/a.py"]) == 2

    assert "pip install 'filepawl[mv]'" in capsys.readouterr().err
    assert (root / "pkg" / "a.py").exists()


def test_rope_refuses_a_destination_that_is_not_a_package(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("rope")
    root = repo(
        {
            "pyproject.toml": policy(mover="rope"),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    (root / "plain").mkdir()
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "plain/a.py"]) == 2

    assert "plain: not a package" in capsys.readouterr().err
    assert (root / "pkg" / "a.py").exists()
    assert not (root / "plain" / "a.py").exists()


def test_rope_refuses_a_destination_directory_that_does_not_exist(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("rope")
    root = repo(
        {
            "pyproject.toml": policy(mover="rope"),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/sub/a.py"]) == 2

    assert "pkg/sub: not a package" in capsys.readouterr().err
    assert not (root / "pkg" / "sub").exists()


def test_rope_backend_moves_the_module_and_rewrites_imports(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("rope")
    root = repo(
        {
            "pyproject.toml": policy(mover="rope"),
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/a.py": "X = 1\n",
            "pkg/b.py": "import pkg.a\n\nprint(pkg.a.X)\n",
        }
    )
    monkeypatch.chdir(root)

    assert main(["mv", "pkg/a.py", "pkg/sub/a.py"]) == 0

    assert (root / "pkg" / "sub" / "a.py").read_text(encoding="utf-8") == "X = 1\n"
    assert not (root / "pkg" / "a.py").exists()
    body = (root / "pkg" / "b.py").read_text(encoding="utf-8")
    assert "import pkg.sub.a" in body
    assert not (root / ".ropeproject").exists()
    capsys.readouterr()


# --- registry ----------------------------------------------------------


def test_builtin_movers_are_registered_by_name() -> None:
    movers = registry.discover_movers()

    assert set(movers) >= {"rope", "command"}
    assert movers["rope"].__name__ == "RopeMover"
    assert movers["command"].__name__ == "CommandMover"


class _FakeEntryPoint:
    def __init__(self, name: str, loader: Callable[[], object]) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> object:
        return self._loader()


def test_entry_point_load_failure_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> object:
        raise ImportError("no such module")

    monkeypatch.setattr(
        registry, "entry_points", lambda group: [_FakeEntryPoint("bad", _boom)]
    )

    with pytest.raises(ConfigError, match="bad"):
        registry.discover_movers()


def test_entry_point_missing_mover_attrs_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotAMover:
        pass

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: [_FakeEntryPoint("incomplete", lambda: _NotAMover)],
    )

    with pytest.raises(ConfigError, match="incomplete"):
        registry.discover_movers()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_entry_point_mover_discovered_from_real_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build a minimal, real installed distribution and prove filepawl
    finds its mover through importlib.metadata, not a mocked
    entry_points()."""
    dist_dir = tmp_path / "dist"
    _write(
        dist_dir / "fakemover" / "__init__.py",
        "class FakeMover:\n"
        "    def move(self, old, new, root):\n"
        "        return []\n"
        "    def find_stale_refs(self, old_dotted, root):\n"
        "        return []\n",
    )
    _write(
        dist_dir / "fakemover-0.1.dist-info" / "METADATA",
        "Metadata-Version: 2.1\nName: fakemover\nVersion: 0.1\n",
    )
    _write(
        dist_dir / "fakemover-0.1.dist-info" / "entry_points.txt",
        "[filepawl.movers]\nfake = fakemover:FakeMover\n",
    )
    monkeypatch.syspath_prepend(str(dist_dir))
    importlib.invalidate_caches()

    movers = registry.discover_movers()

    assert movers["fake"].__name__ == "FakeMover"


def test_a_third_party_mover_name_is_selected_for_the_move(
    repo: Repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []

    class _RecordingMover:
        def move(self, old: Path, new: Path, root: Path) -> list[Path]:
            calls.append((old.name, new.name))
            old.rename(new)
            return [old, new]

        def find_stale_refs(self, old_dotted: str, root: Path) -> list[str]:
            return []

    root = repo(
        {
            "pyproject.toml": policy(mover="recording"),
            "pkg/__init__.py": "",
            "pkg/a.py": "X = 1\n",
        }
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        registry, "discover_movers", lambda: {"recording": _RecordingMover}
    )

    assert main(["mv", "pkg/a.py", "pkg/b.py"]) == 0

    assert calls == [("a.py", "b.py")]
    capsys.readouterr()
