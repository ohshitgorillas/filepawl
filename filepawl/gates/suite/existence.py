"""Existence gate: no test that asserts only that a value exists (design.md §6.18).

A test whose only claim is that a value is there, of some type, or of some
length passes against a stub that returns any value.
"""

from __future__ import annotations

from dataclasses import dataclass

from filepawl.gates.suite.testgate import (
    ABSENCE,
    EXISTENCE,
    TestGate,
    TestNode,
    kind,
    own_asserts,
)


@dataclass
class ExistenceGate(TestGate):
    """Refuses tests whose only claim is that a value exists."""

    name: str = "existence"
    message: str = (
        "asserts only that a value exists — a stub returning any value passes"
        " it too; assert the value"
    )
    clean: str = "asserts a value, so it needs no exemption"

    def fails(self, test: TestNode) -> bool:
        """Return whether a test's asserts are all existence or absence
        assertions, at least one of them existence, and it asserts nothing else."""
        kinds = {kind(node.test) for node in own_asserts(test) or []}
        return EXISTENCE in kinds and kinds <= {EXISTENCE, ABSENCE}
