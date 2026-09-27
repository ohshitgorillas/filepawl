"""Shared fixtures for filepawl tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


def _write_file(path: Path, content: str | int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, int):
        text = "".join(f"line {n}\n" for n in range(1, content + 1))
    else:
        text = content
    path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Callable[[dict[str, str | int]], Path]:
    """Build a synthetic git repository from a {path: content} mapping.

    An int value writes that many lines as "line N\\n"; a str value is
    written verbatim. Parent directories are created as needed. The tree
    is committed with a fixed author so runs are deterministic.
    """

    def make(files: dict[str, str | int]) -> Path:
        root = tmp_path
        for rel, content in files.items():
            _write_file(root / rel, content)

        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(
            root,
            "-c",
            "user.name=filepawl tests",
            "-c",
            "user.email=filepawl-tests@example.invalid",
            "commit",
            "-q",
            "-m",
            "init",
        )
        return root

    return make


_FAKE_CLAUDE = """\
import json
import os
import re
import sys
from pathlib import Path

here = Path(sys.argv[0]).parent
table = json.loads((here / "table.json").read_text(encoding="utf-8"))
calls = here / "calls"
calls.mkdir(exist_ok=True)
number = len(list(calls.iterdir()))
body = sys.stdin.read()
record = {
    "argv": sys.argv[1:],
    "stdin": body,
    "cwd": os.getcwd(),
    "inner": os.environ.get("FILEPAWL_JUDGE_INNER"),
    "claudecode": os.environ.get("CLAUDECODE"),
}
(calls / f"{number:03d}.json").write_text(json.dumps(record), encoding="utf-8")
replies = table["replies"]
reply = replies[min(number, len(replies) - 1)]
if reply.get("exit"):
    sys.exit(reply["exit"])
if "stdout" in reply:
    print(reply["stdout"])
    sys.exit(0)
found = re.findall(r"^### CASE (\\S+)\\nGATE: \\S+\\nFUNCTION: (\\S+)$", body, re.M)
verdicts = table["verdicts"]
answers = [
    {"id": case_id, "verdict": verdicts.get(key, default)[0],
     "reason": verdicts.get(key, default)[1]}
    for default in [["clean", "the failure propagates"]]
    for case_id, key in found
    if key not in reply.get("omit", [])
]
result = reply.get("wrap", "ANSWERS").replace("ANSWERS", json.dumps(answers))
print(json.dumps({"type": "result", "is_error": False, "result": result}))
"""


class FakeClaude:
    """A `claude` executable on `PATH` that answers from a table the test writes.

    `verdicts` maps a case key to its (verdict, reason), and a key it does
    not name is answered clean. Each reply is one call's behavior, the last
    repeating: `exit` exits with that status, `stdout` prints it verbatim,
    `omit` leaves those keys unanswered, and `wrap` places the answer array
    where it says `ANSWERS`.
    """

    def __init__(self, bin_dir: Path) -> None:
        self.bin_dir = bin_dir

    def answer(
        self, verdicts: dict[str, tuple[str, str]], *replies: dict[str, object]
    ) -> None:
        table = {"verdicts": verdicts, "replies": list(replies) or [{}]}
        (self.bin_dir / "table.json").write_text(json.dumps(table), encoding="utf-8")

    def calls(self) -> list[dict[str, object]]:
        folder = self.bin_dir / "calls"
        if not folder.is_dir():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(folder.iterdir())
        ]


@pytest.fixture
def fake_claude(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> FakeClaude:
    """Put a fake `claude` first on `PATH`; until told otherwise it answers clean."""
    bin_dir = tmp_path_factory.mktemp("bin")
    script = bin_dir / "claude"
    script.write_text(f"#!{sys.executable}\n{_FAKE_CLAUDE}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)
    fake = FakeClaude(bin_dir)
    fake.answer({})
    return fake
