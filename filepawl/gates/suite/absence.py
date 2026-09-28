"""Absence gate: no test that asserts only an absent value (design.md §6.11).

A test whose every assertion is that something is absent passes against
code that never ran the feature, because a feature that does nothing
produces exactly that absence.
"""

from __future__ import annotations

from dataclasses import dataclass

from filepawl.gates.suite.testgate import (
    TestGate,
    TestNode,
    is_absence_assertion,
    own_asserts,
)


@dataclass
class AbsenceGate(TestGate):
    """Refuses tests whose only claim is that something is absent."""

    name: str = "absence"
    message: str = (
        "asserts only an absent value — code that never ran the feature passes"
        " it too; assert it beside a case where the feature acts"
    )
    clean: str = "asserts a present value, so it needs no exemption"

    def fails(self, test: TestNode) -> bool:
        """Return whether a test has asserts, all of them absence assertions,
        and asserts nothing else."""
        asserts = own_asserts(test) or []
        return bool(asserts) and all(is_absence_assertion(node) for node in asserts)
