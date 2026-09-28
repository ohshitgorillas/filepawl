"""The `judge` command: policy, cases, calls and report (docs/design.md §7.2)."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from filepawl.cli import main

if TYPE_CHECKING:
    from conftest import FakeClaude

Repo = Callable[[dict[str, str | int]], Path]

ENABLED = "[tool.filepawl.judge]\nenabled = true\n"
HANDLER_RETURN = (
    "def load(path):\n"
    "    try:\n"
    "        return read(path)\n"
    "    except OSError:\n"
    "        return None\n"
)
HANDLER_MOVED = (
    "def load(path):\n"
    "    result = None\n"
    "    try:\n"
    "        result = read(path)\n"
    "    except OSError:\n"
    "        pass\n"
    "    return result\n"
)
TWO_SHAPES = 'def info(ok):\n    if ok:\n        return {"a": 1}\n    return {"b": 2}\n'
TWO_SHAPES_BUILT = (
    'def info(ok):\n    if ok:\n        return {"a": 1}\n    return dict(b=2)\n'
)
DODGE = ("dodge", "the default stands in for the failed read")
FIX = " — fix it on a route the gate traces, or exempt it with a reason"


@pytest.fixture(autouse=True)
def _outer_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FILEPAWL_JUDGE_INNER", raising=False)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _stage(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")


def _silenced(repo: Repo, pyproject: str = ENABLED) -> Path:
    """A repository whose staged change silences a handlers finding in place."""
    root = repo({"pyproject.toml": pyproject, "pkg/io.py": HANDLER_RETURN})
    _stage(root, {"pkg/io.py": HANDLER_MOVED})
    return root


def _exit_code(argv: list[str]) -> object:
    """Return the status `main` exits with when it raises SystemExit."""
    with pytest.raises(SystemExit) as raised:
        main(argv)
    return raised.value.code


def test_a_dodge_prints_its_line_and_exits_one(
    repo: Repo,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = repo(
        {
            "pyproject.toml": ENABLED,
            "pkg/io.py": HANDLER_RETURN,
            "pkg/info.py": TWO_SHAPES,
        }
    )
    _stage(root, {"pkg/io.py": HANDLER_MOVED, "pkg/info.py": TWO_SHAPES_BUILT})
    monkeypatch.chdir(root)
    fake_claude.answer(
        {
            "pkg/io.py::load": DODGE,
            "pkg/info.py::info": ("dodge", "dict() hands back a second shape"),
        }
    )
    code = main(["judge"])
    lines = capsys.readouterr().out.splitlines()
    assert (code, lines) == (
        1,
        [
            "pkg/info.py::info: returns judge: dict() hands back a second shape" + FIX,
            f"pkg/io.py::load: handlers judge: {DODGE[1]}" + FIX,
        ],
    )


def test_a_clean_verdict_exits_zero_and_prints_nothing(
    repo: Repo,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_silenced(repo))
    clean = main(["judge"])
    clean_out = capsys.readouterr().out
    fake_claude.answer({"pkg/io.py::load": DODGE})
    assert (clean, clean_out, main(["judge"]), len(fake_claude.calls())) == (
        0,
        "",
        1,
        2,
    )


def test_a_disabled_policy_exits_zero_without_calling_claude(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _silenced(repo, pyproject="[tool.filepawl.judge]\nenabled = false\n")
    monkeypatch.chdir(root)
    fake_claude.answer({"pkg/io.py::load": DODGE})
    disabled = (main(["judge"]), len(fake_claude.calls()))
    (root / "pyproject.toml").write_text(ENABLED, encoding="utf-8")
    assert (disabled, main(["judge"]), len(fake_claude.calls())) == ((0, 0), 1, 1)


def test_the_default_policy_leaves_the_judge_off(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _silenced(repo, pyproject='[project]\nname = "sample"\n')
    monkeypatch.chdir(root)
    fake_claude.answer({"pkg/io.py::load": DODGE})
    default = (main(["judge"]), len(fake_claude.calls()))
    (root / "pyproject.toml").write_text(ENABLED, encoding="utf-8")
    assert (default, main(["judge"])) == ((0, 0), 1)


def test_an_inner_judge_session_exits_zero_without_calling_claude(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_silenced(repo))
    fake_claude.answer({"pkg/io.py::load": DODGE})
    monkeypatch.setenv("FILEPAWL_JUDGE_INNER", "1")
    inner = (main(["judge"]), len(fake_claude.calls()))
    monkeypatch.delenv("FILEPAWL_JUDGE_INNER")
    assert (inner, main(["judge"]), len(fake_claude.calls())) == ((0, 0), 1, 1)


def test_a_run_with_no_case_makes_no_call(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"pyproject.toml": ENABLED, "pkg/io.py": HANDLER_RETURN})
    monkeypatch.chdir(root)
    fake_claude.answer({"pkg/io.py::load": DODGE})
    _stage(root, {"pkg/io.py": HANDLER_RETURN + "\n\ndef other():\n    return 1\n"})
    persisting = (main(["judge"]), len(fake_claude.calls()))
    _stage(root, {"pkg/io.py": HANDLER_MOVED})
    assert (persisting, main(["judge"]), len(fake_claude.calls())) == ((0, 0), 1, 1)


def test_head_judges_the_last_commit_and_a_root_commit_has_nothing_to_compare(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo({"pyproject.toml": ENABLED, "pkg/io.py": HANDLER_RETURN})
    monkeypatch.chdir(root)
    fake_claude.answer({"pkg/io.py::load": DODGE})
    root_commit = main(["judge", "--head"])
    _stage(root, {"pkg/io.py": HANDLER_MOVED})
    _git(
        root,
        "-c",
        "user.name=filepawl tests",
        "-c",
        "user.email=filepawl-tests@example.invalid",
        "commit",
        "-q",
        "-m",
        "silence",
    )
    assert (root_commit, main(["judge"]), main(["judge", "--head"])) == (0, 0, 1)


def test_the_audit_reports_stale_exemptions_under_pyproject(
    repo: Repo,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = (
        ENABLED + "[tool.filepawl.judge.exempt]\n"
        '"pkg/io.py::load" = "the spec requires silence"\n'
        '"pkg/io.py::gone" = "was here once"\n'
        '"pkg/missing.py::f" = "moved away"\n'
        '"README.md::f" = "not Python"\n'
    )
    monkeypatch.chdir(_silenced(repo, pyproject=pyproject))
    (Path.cwd() / "README.md").write_text("# sample\n", encoding="utf-8")
    _git(Path.cwd(), "add", "README.md")
    fake_claude.answer({"pkg/io.py::load": DODGE})
    where = "pyproject.toml: [tool.filepawl.judge.exempt]"
    code = main(["judge"])
    lines = capsys.readouterr().out.splitlines()
    assert (code, lines, fake_claude.calls()) == (
        1,
        [
            f"{where} 'README.md::f': names no file",
            f"{where} 'pkg/io.py::gone': names no function",
            f"{where} 'pkg/missing.py::f': names no file",
        ],
        [],
    )


def test_a_call_failing_twice_exits_two(
    repo: Repo,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(_silenced(repo))
    fake_claude.answer({}, {"exit": 1})
    code = _exit_code(["judge"])
    err = capsys.readouterr().err
    assert (
        code,
        "filepawl: `claude` failed twice: exited 1" in err,
        len(fake_claude.calls()),
    ) == (2, True, 2)


def test_a_missing_claude_exits_two(
    repo: Repo,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = shutil.which("git")
    assert git is not None
    bin_dir = tmp_path_factory.mktemp("git-only")
    (bin_dir / "git").symlink_to(git)
    monkeypatch.chdir(_silenced(repo))
    monkeypatch.setenv("PATH", str(bin_dir))
    code = _exit_code(["judge"])
    err = capsys.readouterr().err
    assert (code, "filepawl: `claude` is not on PATH" in err) == (2, True)


def test_a_configuration_error_exits_two(
    repo: Repo, fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_silenced(repo, pyproject=ENABLED + "batch = 0\n"))
    assert (_exit_code(["judge"]), fake_claude.calls()) == (2, [])
