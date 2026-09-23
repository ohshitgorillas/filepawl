# filepawl — repository rules

This file is the repository's rule sheet. Procedure lives in the documents it names, read on demand; nothing here restates them. Agent conduct is `~/dev/CLAUDE.md` and is not restated either.

## Spec authority

`docs/design.md` is the specification. Code matches it or the spec changes first: a departure lands as an edit to `docs/design.md` in the same commit as the code, named in the commit message, never as code that quietly disagrees. An open question the spec does not settle goes to the owner before the code that depends on it is written; it is not resolved by picking.

The implementation plan, once written, lives at `docs/plan.md`. A session resuming work reads the plan from that file.

## Ported behavior has a source of truth

The length gate and the ratchet are extractions, not inventions. Where the spec is silent on a detail of their behavior, the three existing scripts decide, and they are read before the detail is coded:

- `~/dev/hqptuner/scripts/gates/check_file_length.py`, tests `~/dev/hqptuner/tests/gates/test_file_length_ratchet.py`
- `~/dev/triviajudge/scripts/gates/check_file_length.py`, tests `~/dev/triviajudge/tests/gates/test_check_file_length.py`
- `~/dev/gauntlet/scripts/gates/file-length.py`, cases in `~/dev/gauntlet/scripts/gates/file_length_selftest.py`

The barrels gate is an extraction the same way, from:

- `~/dev/hqptuner/scripts/gates/check_no_barrels.py`, tests `~/dev/hqptuner/tests/gates/test_no_barrels.py`
- `~/dev/triviajudge/scripts/gates/code/check_no_barrels.py`, tests `~/dev/triviajudge/tests/gates/test_check_no_barrels.py`
- `~/dev/gauntlet/scripts/gates/code/no-barrels.py`, cases in `~/dev/gauntlet/scripts/gates/code/no_barrels_selftest.py`

Where the three disagree, the spec's decisions table rules; where it too is silent, the disagreement goes to the owner with the three behaviors quoted.


## Consumer repositories are read-only

`~/dev/hqptuner`, `~/dev/gauntlet` and `~/dev/triviajudge` are read freely and written never during this build. Migration is `docs/design.md` §10, one PR per repository, on the owner's word for each.

## Tests

Every behavior is written test-first: a red test in `tests/`, then the code that turns it green, in the same commit. Tests run on synthetic trees under `tmp_path` with a real `git init`; a test that stubs `git ls-files` tests nothing this package does. No test reads a consumer checkout.

No test waits on a wall clock.

## Gates

`make check` is the bar and is green before every commit: `ruff check`, `black --check`, `mypy --strict filepawl`, `pytest -q`, and `filepawl check` over this tree with default policy. Pre-commit runs the same gates, and the repository's `.pre-commit-config.yaml` consumes `.pre-commit-hooks.yaml` from this checkout so the hook definition is exercised by its own commits.

Self-application is a gate, not a courtesy. filepawl's own tree carries no `exempt` entry and, by intent, no allowance entry: a module here that crosses the watch line is split, and a case where splitting is wrong goes to the owner before `accept` is run on this tree.

Tools live in `.venv/bin` and are configured in `pyproject.toml`. `--no-verify`, `SKIP=` and hook-config edits stay off the table.

## Dependencies

Runtime: `tomli-w` only. `rope` under the `mv` extra only; core imports it lazily and `filepawl mv` with `mover = "rope"` and no rope installed exits 2 with the install line. No `click`, no `rich`, no `pydantic`. Python floor 3.12, declared in `pyproject.toml` and not raised.

## Markdown

Soft-wrapped: one paragraph, list item or blockquote per logical line. `docs/` and `README.md` are full English; no trivia, no decision archaeology. Decisions go in the commit message and, when they change a rule, in `docs/design.md`.

## Commits

Prefixes: `feat:`, `fix:`, `test:`, `docs:`, `chore:`. One plan task per commit; a commit that lands a task names it. A spec edit that a code change requires rides in that commit under the code's prefix, and the message says which section moved.

## Delegation, this repository

Rote: porting a named case from one of the three suites to pytest under `tests/`, with the source case cited. Judgment, never delegated: gate semantics, state file format, CLI exit codes, the mover, anything touching `docs/design.md`.
