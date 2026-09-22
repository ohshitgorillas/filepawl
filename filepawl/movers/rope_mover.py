"""The rope backend: move a module and rewrite its importers (§8).

rope is an optional extra. It is imported inside `move`, in the
`import rope.base.project` form, so that an absent (or stubbed-out)
`rope` package raises `ImportError` even when a submodule is already in
`sys.modules`, and so that importing filepawl costs nothing when the
extra is not installed.
"""

from __future__ import annotations

from pathlib import Path

from filepawl.errors import FilepawlError
from filepawl.movers.base import BaseMover, relative_to_root

_INSTALL = "rope is not installed; run: pip install 'filepawl[mv]'"


class RopeMover(BaseMover):
    """`MoveModule` over the project rooted at the repository.

    rope's `MoveModule` moves a module into a destination package; it
    does not rename. `new` therefore has to keep `old`'s basename and sit
    in a directory that already carries an `__init__.py` (or be the
    project root, which rope treats as a source folder). Both are refused
    up front rather than surfacing as a rope traceback, and no directory
    is created on the way: a destination package is the author's to make.

    The project is opened with `ropefolder=None` so no `.ropeproject`
    directory is written into the repository under test.
    """

    def move(self, old: Path, new: Path, root: Path) -> list[Path]:
        try:
            # rope ships no py.typed, and it is an optional extra: the
            # ignores keep `mypy --strict` honest about the rest.
            import rope.base.project  # type: ignore[import-untyped]
            import rope.refactor.move  # type: ignore[import-untyped]
        except ImportError as exc:
            raise FilepawlError(_INSTALL) from exc

        if old.name != new.name:
            raise FilepawlError(
                f"rope moves a module into a package without renaming it: "
                f"{new.name!r} must be {old.name!r}"
            )
        destination = new.parent
        folder = relative_to_root(destination, root)
        at_root = folder in ("", ".")
        if not at_root and not (destination / "__init__.py").is_file():
            raise FilepawlError(f"{folder}: not a package")

        project = rope.base.project.Project(str(root), ropefolder=None)
        try:
            resource = project.get_resource(relative_to_root(old, root))
            target = project.root if at_root else project.get_resource(folder)
            mover = rope.refactor.move.create_move(project, resource)
            changes = mover.get_changes(target)
            changed = [root / change.resource.path for change in changes.changes]
            project.do(changes)
        except FilepawlError:
            raise
        except Exception as exc:  # rope raises its own exception hierarchy
            raise FilepawlError(f"rope move failed: {exc}") from exc
        finally:
            project.close()
        return changed
