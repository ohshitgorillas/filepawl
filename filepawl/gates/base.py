"""Gate protocol and the Finding record every gate emits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from filepawl.config import Policy
from filepawl.state import State
from filepawl.tree import Tree


@dataclass(frozen=True, order=True)
class Finding:
    """One line of `filepawl check` output."""

    path: str
    message: str
    fixable_by_accept: bool = False


class Gate(Protocol):
    """A check over the tree; stateless gates return `state` unchanged from `accept`."""

    name: str

    def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]: ...

    def accept(self, tree: Tree, policy: Policy, state: State) -> State: ...
