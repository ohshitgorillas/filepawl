"""Git-backed tree scan, include-glob matching and test-path classification.

See docs/design.md §4 (the glob note on dot-directories), §6.1 (line
measurement) and §6.3 (scope of a run).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from filepawl.errors import ConfigError

if TYPE_CHECKING:
    from filepawl.config import Policy


def glob_match(pattern: str, path: str) -> bool:
    """Match a posix-relative path against a `pyproject.toml` include glob.

    Written by hand-translating the pattern to a regex (no `fnmatch`, no
    `pathlib.match`) so that `**` can mean "zero or more path segments,
    including dot-directories" and a bare `*` never crosses `/`.
    """
    regex = _translate(pattern)
    return re.fullmatch(regex, path) is not None


def _translate(pattern: str) -> str:
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*" and i + 1 < n and pattern[i + 1] == "*":
            before_slash = i == 0 or pattern[i - 1] == "/"
            after_idx = i + 2
            after_slash = after_idx >= n or pattern[after_idx] == "/"
            if before_slash and after_slash:
                if after_idx < n:
                    # "**/" (leading or mid-pattern): zero or more segments.
                    out.append("(?:.*/)?")
                    i = after_idx + 1
                    continue
                # "**" at the end of the pattern, e.g. "tests/**".
                out.append(".*" if i == 0 else ".+")
                i = after_idx
                continue
            # "**" not on a segment boundary: treat as two lone stars.
            out.append("[^/]*[^/]*")
            i = after_idx
            continue
        if char == "*":
            out.append("[^/]*")
            i += 1
            continue
        out.append(re.escape(char))
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class Tree:
    """A scanned repository tree, filtered to the configured include globs."""

    root: Path
    files: tuple[str, ...]
    selected: tuple[str, ...] | None
    tests: tuple[str, ...]
    languages: dict[str, tuple[str, ...]]

    def is_test(self, path: str) -> bool:
        return any(glob_match(pattern, path) for pattern in self.tests)

    def language_of(self, path: str) -> str | None:
        for name, include in self.languages.items():
            if any(glob_match(pattern, path) for pattern in include):
                return name
        return None

    def line_count(self, path: str) -> int:
        text = (self.root / path).read_text(encoding="utf-8")
        return len(text.splitlines())

    def measured(self) -> tuple[str, ...]:
        return self.selected if self.selected is not None else self.files


def find_root(start: Path) -> Path:
    """Resolve the git repository root containing `start`.

    Raises `ConfigError` when git is missing or `start` is not inside a
    repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigError(f"not a git repository: {start}") from exc
    return Path(result.stdout.strip())


def _selected_paths(files: tuple[str, ...], paths: list[str]) -> tuple[str, ...]:
    result: set[str] = set()
    for raw in paths:
        normalized = PurePosixPath(raw).as_posix()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.rstrip("/")
        for candidate in files:
            if candidate == normalized or candidate.startswith(normalized + "/"):
                result.add(candidate)
    return tuple(sorted(result))


def build_tree(root: Path, policy: Policy, paths: list[str] | None = None) -> Tree:
    """Scan `git ls-files` under `root`, filtered by every language's include globs."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    all_files = [name for name in result.stdout.decode("utf-8").split("\x00") if name]
    includes = [
        pattern
        for language_policy in policy.languages.values()
        for pattern in language_policy.include
    ]
    files = tuple(
        sorted(name for name in all_files if any(glob_match(g, name) for g in includes))
    )
    languages = {
        name: tuple(language_policy.include)
        for name, language_policy in policy.languages.items()
    }
    selected = None if paths is None else _selected_paths(files, paths)
    return Tree(
        root=root,
        files=files,
        selected=selected,
        tests=tuple(policy.tests),
        languages=languages,
    )
