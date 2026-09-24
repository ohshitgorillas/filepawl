"""The Claude Code plugin under `plugin/` (docs/design.md §7.1)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin"
SCRIPT = PLUGIN / "hooks" / "filepawl-hook.sh"


def run_script(
    project: Path, path_dirs: list[Path]
) -> subprocess.CompletedProcess[str]:
    env = {
        "CLAUDE_PROJECT_DIR": str(project),
        "PATH": os.pathsep.join([*map(str, path_dirs), "/usr/bin", "/bin"]),
    }
    return subprocess.run(
        ["sh", str(SCRIPT)],
        input="{}",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def fake_filepawl(directory: Path, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "filepawl"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_marketplace_lists_the_plugin_directory() -> None:
    marketplace = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    [entry] = marketplace["plugins"]
    assert entry["name"] == "filepawl"
    assert (REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_hooks_json_runs_the_script_before_write_edit_and_multiedit() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    [group] = hooks["hooks"]["PreToolUse"]
    assert set(group["matcher"].split("|")) == {"Write", "Edit", "MultiEdit"}
    [command] = group["hooks"]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/filepawl-hook.sh" in command["command"]


def test_no_filepawl_anywhere_is_silent_and_exits_zero(tmp_path: Path) -> None:
    result = run_script(tmp_path / "project", [tmp_path / "empty"])
    assert result.returncode == 0
    assert result.stdout == ""


def test_project_venv_is_preferred_over_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    fake_filepawl(project / ".venv" / "bin", 'echo "venv $1"')
    fake_filepawl(tmp_path / "onpath", 'echo "path $1"')
    result = run_script(project, [tmp_path / "onpath"])
    assert result.stdout == "venv hook\n"


def test_path_is_used_when_the_project_has_no_venv(tmp_path: Path) -> None:
    fake_filepawl(tmp_path / "onpath", 'echo "path $1"')
    result = run_script(tmp_path / "project", [tmp_path / "onpath"])
    assert result.stdout == "path hook\n"


def test_filepawl_exiting_two_does_not_block(tmp_path: Path) -> None:
    fake_filepawl(tmp_path / "onpath", "echo usage >&2; exit 2")
    result = run_script(tmp_path / "project", [tmp_path / "onpath"])
    assert result.returncode == 0
