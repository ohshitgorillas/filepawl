"""Directory-count gate: files-per-directory cap (design.md §6.2)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import State
from filepawl.tree import Tree


def _directory_of(path: str) -> str:
    slash = path.rfind("/")
    return path[:slash] if slash != -1 else "."


@dataclass
class DircountGate:
    """Caps the number of include-matched files directly in one directory."""

    name: str = "dircount"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        counted: dict[str, list[str]] = defaultdict(list)
        for path in tree.files:
            directory = _directory_of(path)
            basename = path.rsplit("/", 1)[-1]
            if basename in policy.dircount.exclude:
                continue
            counted[directory].append(path)

        findings = []
        for directory, paths in counted.items():
            cap = self._cap_for(paths, tree, policy)
            count = len(paths)
            if count > cap:
                findings.append(
                    Finding(path=directory, message=f"{count} files, cap {cap}")
                )
        return sorted(findings)

    def _cap_for(self, paths: list[str], tree: Tree, policy: Policy) -> int:
        is_test_dir = any(tree.is_test(path) for path in paths)
        return policy.dircount.cap_tests if is_test_dir else policy.dircount.cap

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        return state
