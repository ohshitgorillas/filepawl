"""Length gate: hard cap plus the one-way ratchet (docs/design.md §6.1, §7).

Cap and ratchet are read off the same number and are checked independently:
a file over the cap with no allowance entry reports both, as all three of
the source scripts this gate extracts do. The stale audit runs over the
whole allowance table however the measured set was narrowed (§6.3).
"""

from __future__ import annotations

from filepawl.config import Policy
from filepawl.gates.base import Finding
from filepawl.state import Entry, State
from filepawl.tree import Tree


class LengthGate:
    """The cap and the ratchet, over one tree, one policy and one state."""

    name = "length"

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]:
        findings: list[Finding] = []
        for path in tree.measured():
            findings += self._file_findings(path, tree, policy, state)
        findings += self._stale_findings(tree, policy, state)
        findings += self._exempt_findings(tree, policy)
        return findings

    def accept(self, tree: Tree, policy: Policy, state: State) -> State:
        """Add missing entries, lower shrunk ones, drop stale ones.

        Never raises an entry and never raises an exception: a file that
        grew keeps its entry, and the finding survives the run.
        """
        watch = policy.length.watch
        allowance = {
            path: entry
            for path, entry in state.allowance.items()
            if self._stale_reason(path, tree, watch) is None
        }
        for path in tree.measured():
            if tree.is_test(path):
                continue
            lines = tree.line_count(path)
            if lines <= watch:
                continue
            entry = allowance.get(path)
            if entry is None:
                allowance[path] = Entry(lines=lines)
            elif lines < entry.lines:
                allowance[path] = Entry(lines=lines, reason=entry.reason)
        return State(version=state.version, allowance=allowance)

    def _file_findings(
        self, path: str, tree: Tree, policy: Policy, state: State
    ) -> list[Finding]:
        length = policy.length
        lines = tree.line_count(path)
        exempt = path in policy.exempt
        findings: list[Finding] = []

        if tree.is_test(path):
            if not exempt and lines > length.cap_tests:
                findings.append(
                    Finding(
                        path=path,
                        message=(f"test over cap {length.cap_tests} ({lines} lines)"),
                    )
                )
            return findings

        if not exempt and lines > length.cap:
            findings.append(
                Finding(
                    path=path,
                    message=f"over cap {length.cap} ({lines} lines); split it",
                )
            )

        if lines <= length.watch:
            return findings

        entry = state.allowance.get(path)
        if entry is None:
            findings.append(
                Finding(
                    path=path,
                    message=(
                        f"over watch line {length.watch} ({lines} lines); "
                        f"run `filepawl accept {path}`"
                    ),
                    fixable_by_accept=True,
                )
            )
        elif lines > entry.lines:
            findings.append(
                Finding(
                    path=path,
                    message=(
                        f"grew past allowance ({lines} > {entry.lines}); split it"
                    ),
                )
            )
        elif lines < entry.lines:
            findings.append(
                Finding(
                    path=path,
                    message=(
                        f"shrank ({lines} < {entry.lines}); "
                        f"run `filepawl accept {path}`"
                    ),
                    fixable_by_accept=True,
                )
            )
        return findings

    def _stale_findings(
        self, tree: Tree, policy: Policy, state: State
    ) -> list[Finding]:
        watch = policy.length.watch
        findings: list[Finding] = []
        for path in sorted(state.allowance):
            reason = self._stale_reason(path, tree, watch)
            if reason is not None:
                findings.append(
                    Finding(path=path, message=reason, fixable_by_accept=True)
                )
        return findings

    def _stale_reason(self, path: str, tree: Tree, watch: int) -> str | None:
        """Why an allowance entry cannot stand, or None when it can.

        The three conditions are mutually exclusive and tried in this
        order, as in the source scripts' `stale()`.
        """
        if not _in_tree(tree, path):
            return "allowance names a path outside the tree; drop it"
        if tree.is_test(path):
            return "allowance names a test path; drop it"
        if tree.line_count(path) <= watch:
            return f"back under watch line {watch}; drop it"
        return None

    def _exempt_findings(self, tree: Tree, policy: Policy) -> list[Finding]:
        return [
            Finding(path=path, message="exempt names a path outside the tree")
            for path in sorted(policy.exempt)
            if not _in_tree(tree, path)
        ]


def _in_tree(tree: Tree, path: str) -> bool:
    """Whether a path is in the scanned tree.

    `build_tree` has already filtered `git ls-files` through the include
    globs and through existence on disk, so membership is the whole test.
    """
    return path in tree.files
