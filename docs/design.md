# filepawl — design

Date: 2026-09-21

Status: implemented; migration of consumers pending (§10).

## 1. Purpose

Three repositories (HQPTuner, Gauntlet, Trivia Judge) each carry a hand-rolled copy of one Python script: a file-length cap plus a one-way ratchet on files above a watch line. The copies share a core and have drifted at the edges (`CAP_EXEMPT`, `--check`, `git ls-files` default, per-entry comments, JS/CSS coverage). Every fix is made three times. The ratchet state (`ALLOWANCE`, `CAP_EXEMPT`) lives inside the script, so an engine fix must be hand-merged around per-repository state.

filepawl extracts the engine into one installable package with:

- a CLI, so agents mutate ratchet state through commands rather than editing a table by hand;
- policy separated from state;
- a second gate against flat directory structure (files per directory, cap only);
- a third gate against splits that leave a shell behind (re-export modules and trivial forwarders), extracted from the `no-barrels` script the three repositories also each carry;
- a fourth gate against functions that nest blocks too deep, extracted from the `nesting` script the three repositories also each carry;
- a `mv` command that moves a file and rewrites imports, with pluggable per-language backends;
- gate and mover registries so users can add their own.

Out of scope: Trivia Judge's suite-time ratchet (`check_suite_time.py`), a Claude Code plugin wrapper, PyPI publication.

## 2. Decisions taken

| Question | Decision |
|---|---|
| Form | pip-installable package with CLI; consumable via pre-commit `repo:`, Makefile, CI |
| Directory gate | files per directory, non-recursive, cap only, no ratchet |
| Policy vs state | split: policy in `pyproject.toml` `[tool.filepawl]`, state in `.filepawl.toml` |
| Raising an allowance | no command exists; `accept` only adds or lowers |
| Cap exemptions | live in policy, human-edited; no `exempt` command |
| Mover | depend on rope (optional extra), do not vendor; `command` backend as escape hatch; entry-point backends for third parties |
| Distribution | GitHub tags for now; consumers pin `rev:`; PyPI later without consumer changes beyond install line |
| Python floor | 3.12 (`tomllib` in stdlib; consumers declare `>=3.12` or nothing) |
| Teaching agents | `check` failure output prints the exact `filepawl accept` command; one line in each consumer `CLAUDE.md` |
| Architecture | gate registry (A): each gate is a class; built-ins plus `filepawl.gates` entry points |
| Barrels gate | built-in, enabled by default, Python only (`ast`); rules ported unwidened from the three `no-barrels` scripts |
| Barrels file set | tree files matched by the gate's own `include`, minus test paths; whole tree every run |
| Barrels forwarder scope | `forwarders` globs, default every checked file; a repository with thin adapter layers narrows it |
| Barrels exemptions | live in policy, human-edited, with a reason; no command writes them, and a stale one fails |
| Nesting gate | built-in, enabled by default, Python only (`ast`); rules ported unwidened from the three `nesting` scripts |
| Nesting file set | tree files matched by the gate's own `include`, test paths included; whole tree every run |
| Nesting limit | `max_depth`, default 4, the limit all three scripts hold |
| Nesting exemptions | live in policy, per function, human-edited, with a reason; no command writes them, and a stale one fails |

Rationale for cap-only directory gate: the ratchet exists to stop files parking against the cap because trimming two lines is always cheaper than splitting. Moving a file into a subpackage is cheap (tool-assisted import rewrite), so the crawl dynamic does not apply to directories.

## 3. Package layout

```
filepawl/
  __init__.py
  cli.py            # argparse: check, accept, init, mv
  cli_mv.py         # the mv command: language block, mover, stale refs, state
  config.py         # load [tool.filepawl], merge defaults, validate
  state.py          # read/write .filepawl.toml
  tree.py           # git ls-files, include globs, test-path classification
  gates/
    __init__.py
    base.py         # Gate protocol, Finding dataclass
    length.py       # cap + ratchet
    dircount.py     # files-per-directory cap
    barrels.py      # re-export modules and trivial forwarders
    nesting.py      # block depth per function
    registry.py     # built-ins + entry points
  movers/
    __init__.py
    base.py         # Mover protocol, shared stale-reference grep
    rope_mover.py   # optional extra [mv]
    git_mover.py    # plain `git mv`, the default for a block with no mover
    command.py      # {old}/{new} shell template
    registry.py
tests/
pyproject.toml      # deps: tomli-w; extras: mv = [rope]
.pre-commit-hooks.yaml
README.md
```

Dependencies: `tomli-w` in core. `rope` under extra `mv`. No click; argparse.

## 4. Configuration (policy)

`pyproject.toml`. Every key optional; defaults shown.

```toml
[tool.filepawl]
languages = ["python"]
tests = ["tests/**"]

[tool.filepawl.length]
cap = 500
cap_tests = 800
watch = 400

[tool.filepawl.dircount]
cap = 15
cap_tests = 30
exclude = ["__init__.py"]

[tool.filepawl.exempt]
# path = reason. Human-edited. Exempts from the hard cap only; the file still
# needs an allowance entry and may not grow.
# "scripts/junkcal_fixture.py" = "junkcal fixture oracle, provenance kept whole"

[tool.filepawl.barrels]
include = ["**/*.py"]
forwarders = ["**"]

[tool.filepawl.barrels.module_exempt]
# path = reason. Human-edited. A module that defines nothing on purpose.

[tool.filepawl.barrels.forwarder_exempt]
# "path::function" = reason. Human-edited. A forwarder that is the right shape.
# "hqptuner/presets/presetops.py::park_filter" = "reaches the private filter park"

[tool.filepawl.nesting]
include = ["**/*.py"]
max_depth = 4

[tool.filepawl.nesting.exempt]
# "path::qualified.name" = reason. Human-edited. A function that nests past the limit on purpose.

[tool.filepawl.python]
include = ["**/*.py"]
mover = "rope"

[tool.filepawl.javascript]
include = ["**/*.js", "**/*.css"]
mover = "command"
mover_command = "npx jscodeshift -t scripts/move.js --old {old} --new {new} src/"
```

`**` matches dot-directories: HQPTuner ratchets `.claude/hooks/*.py`, and `git ls-files` lists them, so the glob must too.

A language block with no `mover` gets plain `git mv` plus a stale-reference grep. An unknown `mover` name is a config error (exit 2). Language block names are free-form; the built-in defaults exist only for `python`.

## 5. State

`.filepawl.toml` at repository root, committed, CLI-owned.

```toml
# Generated by filepawl. Do not edit; run `filepawl accept`.
version = 1

[allowance]
"hqptuner/conf/matrixconf.py" = { lines = 496 }
"triviajudge/core.py" = { lines = 444, reason = "Line record plus its readers" }
```

`reason` is optional, written by `filepawl accept <path> --reason "..."`, and preserved when a later `accept` lowers the entry. The file is rewritten wholesale on every `accept`; the header comment is regenerated. Entries are sorted by path so diffs are stable.

## 6. Gate semantics

### 6.1 Length gate

A file's length is `len(path.read_text(encoding="utf-8").splitlines())`: a trailing newline adds no line, and `\r\n` counts as one. This is what the three existing scripts measure (Trivia Judge already passes `utf-8`; the other two use the locale default), so `init` reproduces their tables exactly. It is not `wc -l`.

For each file in the include set:

- Test path (matches a `tests` glob): must be at or under `cap_tests`. No ratchet.
- Non-test path: must be at or under `cap`, unless listed in `exempt`.
- Non-test path over `watch`: must have an allowance entry.
  - `lines > entry`: fail, "grew past allowance; split it".
  - `lines < entry`: fail, "shrank; run `filepawl accept <path>`".
  - `lines == entry`: pass.
- Exempt path still requires an allowance entry and follows the same grow/shrink rules; the exemption removes only the cap check.

Stale audit, always over the whole allowance table regardless of argv:

- entry names a path outside the tree (`git ls-files` filtered through the include globs, then through existence on disk): fail, "drop it". An untracked file on disk and a tracked file deleted from disk are both outside the tree;
- entry names a test path: fail;
- entry names a file now at or under `watch`: fail, "back under watch line";
- `exempt` names a path not in the tree: fail (config drift).

`accept` fixes the first three stale conditions; `check` names the command. Exempt drift is policy, fixed by hand in `pyproject.toml`.

### 6.2 Directory-count gate

For each directory that contains at least one include-matched file: count the include-matched files directly in it, minus names in `exclude`. Over `cap` (or `cap_tests` when any include-matched file directly in the directory matches a `tests` glob) fails, naming the directory and the count. Recursion is not counted; subdirectories are their own directories. No state, no ratchet.

### 6.3 Scope of a run

`filepawl check` with no paths scans `git ls-files` filtered through every language's `include` globs. Paths on argv narrow the length gate's measured set only. The stale audit, the directory gate, the barrels gate and the nesting gate always run over the whole tree, because a directory count over a subset is meaningless and an exemption audit over a subset calls live entries stale.

`.pre-commit-hooks.yaml` declares the hook with `pass_filenames: false` and `always_run: true`: one hook covers every language, where HQPTuner today needs a `types: [python]` hook and a `types: [javascript]` hook and checks CSS only from `make`. The whole-tree run is one `git ls-files` plus a line count per file, so nothing is saved by narrowing it.

### 6.4 Output and exit codes

One line per finding: `path: message`. Findings sorted by path. If any finding is fixable by `accept`, the last line prints the exact command. Exit 0 clean, 1 findings, 2 configuration or state error (unparseable TOML, unknown key, unknown mover, missing `git`).

### 6.5 Gate registry

`Gate` protocol: `name: str`; `run(tree, policy, state) -> list[Finding]`; `accept(tree, policy, state) -> state` (identity for stateless gates). `Finding` carries `path`, `message`, `fixable_by_accept: bool`. Built-ins register in `gates/registry.py`; third parties register under the `filepawl.gates` entry-point group. All discovered gates run on every `check`; a `[tool.filepawl.<gate>]` table with `enabled = false` disables one.

### 6.6 Barrels gate

A split moves code. It does not leave a shell behind that points at where the code went. Both shapes below make a file shorter without making the tree simpler, and both read as a completed split to the length gate. The tell they share is that no caller changed. That is not directly checkable, so the gate checks the two syntactic shapes it comes in.

Checked files: tree files matched by `[tool.filepawl.barrels] include`, minus test paths. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped: syntax is the compiler's gate, and a file that does not parse has no shape to judge.

Re-export module: a module whose body carries an `import` or `from ... import` statement and defines nothing. Defining something means a function, an async function, a class, or an assignment at module level other than to `__all__`. A module whose logic sits only under `if __name__ == "__main__":` defines nothing. `__init__.py` is never a re-export module, since re-exporting a package's surface is its job. Finding: `path: imports and defines nothing — a re-export module is not a split`.

Trivial forwarder, checked only in files matched by a `forwarders` glob: a function or method, at any nesting depth, whose body, after an optional leading docstring, is a single `return` of a call, seen through one `await`. The callee is an attribute chain rooted at a plain name, and the call passes exactly the function's positional parameters, in order, as bare names, with no keywords and no starred arguments. When the chain is rooted at the first parameter, that parameter is spent on the chain and is not expected among the arguments. Finding: `path::function: returns a call on its own arguments — move the callers, not the method`.

The rules are not widened. A forwarder that passes an argument by keyword and one whose chain is rooted in a call (`self.require_http().restore(x)`) are not caught. Catching them cost more false positives than the hits were worth in the three source repositories, and review catches them.

Exemptions live in policy with a reason. `module_exempt` keys are paths; `forwarder_exempt` keys are `path::function`. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- a `module_exempt` entry whose module is not a re-export module: `the module defines something, so it needs no exemption`;
- a `forwarder_exempt` entry naming no forwarder in its file: `matches no forwarder`. The forwarder test here ignores `forwarders` scope, as the source scripts do.

No barrels finding is fixable by `accept`, and `accept` leaves state unchanged.

### 6.7 Nesting gate

Cyclomatic complexity counts branches, not indentation. A long function that is deeply nested but branch-cheap scores fine under ruff `C901` and xenon, and is still unreadable: every line in it carries four or five conditions the reader has to hold at once. The nesting gate measures indentation directly. It is the Python peer of eslint's `max-depth`.

Checked files: tree files matched by `[tool.filepawl.nesting] include`, test paths included, since all three source scripts measure tests. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

Depth is counted per function. The function body is not itself a level. A level is an `if`, `for`, `while`, `with`, `try` or `match`, async forms included. A statement anywhere in any branch of a block (`else`, `except`, `finally`, a `case` arm) sits one level inside that block. Two shapes do not add a level:

- `elif` shares its `if`'s level, because a chain of arms is flat to a reader however many there are. A plain `else:` whose body is an `if` is a real level. The parser gives both the same tree; the column of the inner `if` tells them apart.
- A nested `def` starts its own count at zero, because its reader does not carry the outer function's conditions. It does not raise the outer function's depth.

Functions are named by qualified name: class and enclosing-function names joined with `.`, as in `C.method` or `outer.inner`. A function nesting deeper than `max_depth` fails. Finding: `path::qualified.name: nests N deep (max M) — flatten the function`.

Exemptions live in `[tool.filepawl.nesting.exempt]`, keyed `path::qualified.name`, with a reason. An entry covers every function its key names. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- an entry naming no function in its file: `names no function`;
- an entry whose functions all nest within the limit: `nests N deep, within the limit of M`, where N is the deepest of them.

No nesting finding is fixable by `accept`, and `accept` leaves state unchanged.

## 7. CLI

```
filepawl check [PATH...]
filepawl accept [PATH...] [--reason TEXT]
filepawl init
filepawl mv OLD NEW
```

- `check`: section 6.
- `accept`: for each watched non-test file (all of them when no path given): add a missing entry at current length, lower an entry whose file shrank, drop stale entries. Refuses to raise an entry: a file that grew prints the same "grew past allowance; split it" finding and exits 1. `--reason` with exactly one path sets that entry's reason.
- `init`: write `.filepawl.toml` from the current tree (equivalent to `accept` on empty state) and, if `[tool.filepawl]` is absent, append a commented default policy block to `pyproject.toml`. Refuses to overwrite an existing state file.
- `mv`: section 8.

## 8. Mover

`Mover` protocol: `move(old: Path, new: Path, root: Path) -> list[Path]` (files changed) and `find_stale_refs(old_dotted: str, root: Path) -> list[str]` (`path:line: text` hits).

`filepawl mv OLD NEW`:

1. Resolve the language block whose `include` matches `OLD`; pick its mover. 2. Run the mover. `rope_mover` uses rope's `MoveModule` over the project; `command` renders `mover_command` with `{old}` and `{new}` — shell-quoted, since the rendered template goes to a shell — and runs it via the shell, failing on non-zero exit; no mover means `git mv`. 3. Grep the tree for the old dotted module path and the old relative path as a string (catches `importlib`, `mock.patch("pkg.mod.fn")`, entry points, `pyproject.toml` references). Print hits as leftovers; do not edit them. 4. If the file had an allowance entry, move the entry to the new path. 5. Exit 0 when the move ran, even with leftovers; leftovers are printed and counted so an agent can act on them.

Third-party movers register under the `filepawl.movers` entry-point group and are selected by name in `mover =`.

## 9. Testing

- Unit tests per gate on synthetic trees built in `tmp_path` with a real `git init` so `git ls-files` behaviour is exercised.
- Port the scenario coverage from the three existing suites: HQPTuner 33 pytest cases, Trivia Judge 16 pytest cases, Gauntlet 19 cases inside one hand-rolled `self_test()` that must be rewritten as pytest: cap pass/fail at both limits, watch-line entry required, grow fails, shrink fails, exact match passes, each stale condition, exempt file at cap and growing, multiple offenders reported together, test files exempt from ratchet.
- Directory gate: at cap, over cap, `__init__.py` excluded, nested directories counted separately, tests cap applied.
- Barrels gate: port the cases of HQPTuner's `tests/gates/test_no_barrels.py`, Trivia Judge's `tests/gates/test_check_no_barrels.py` and Gauntlet's `no_barrels_selftest.py`. Scope cases are expressed through `forwarders`, and exemption cases through policy.
- Nesting gate: port the cases of HQPTuner's `tests/gates/test_nesting.py`, Trivia Judge's `tests/gates/test_check_nesting.py` and Gauntlet's `nesting_selftest.py`. Cases on the `depths` seam are expressed as findings at a limit that exposes the measured depth, and exemption cases through policy.
- `accept`: adds, lowers, refuses to raise, drops stale, preserves reason, stable sort.
- `init`: fresh tree, refuses overwrite, appends policy stub once.
- `mv`: `command` backend with a fake script; `rope` backend behind `pytest.importorskip("rope")`; stale-ref grep finds a `mock.patch` string.
- Registry: an entry-point gate and mover discovered from a test-installed distribution.
- Self-application: filepawl's own tree passes `filepawl check` with default policy; the repository's pre-commit runs it.

## 10. Migration of the three consumers

Per repository, one PR:

1. Add `filepawl` to dev dependencies (git URL pinned to a tag) and a pre-commit entry `repo: https://github.com/ohshitgorillas/filepawl`, `rev: vX.Y.Z`, hook `filepawl`. 2. Write `[tool.filepawl]` in `pyproject.toml` only where the repository departs from defaults: HQPTuner adds a `javascript` block and the `junkcal_fixture.py` exemption; Gauntlet adds `**/*.sh` to `include`. For the barrels gate, HQPTuner sets `include` to `hqptuner/**/*.py` and `scripts/**/*.py`, `forwarders` to its `core`, `lanes`, `presets`, `engine` and `conf` packages, and carries its two `presetops.py` forwarder exemptions over with their reasons. Trivia Judge sets `include` and `forwarders` to `triviajudge/**` and `scripts/**`. Gauntlet sets `include` to `hooks/**/*.py` and `scripts/**/*.py`. Gauntlet's script also reads untracked files, and filepawl does not. The nesting gate needs no policy in any of the three: its default `include` is the file set all three measure, and none carries a nesting exemption. 3. Run `filepawl init`. Existing `ALLOWANCE` values need no import: the old ratchet already forced exact equality with current lengths, so `init` reproduces them. Carry Trivia Judge's per-entry comments over with `filepawl accept <path> --reason "..."`. 4. Run `filepawl check`; expect clean. Directory gate may surface new findings; those are decided per repository, not silently exempted. 5. Delete the old length, barrels and nesting scripts, their tests, and their Makefile / pre-commit / gate-runner wiring. Replace the CONTRIBUTING and CLAUDE.md prose with one line pointing at `filepawl check` and `filepawl accept`.

## 11. Open items deferred

- Claude Code plugin (skill plus a hook denying edits to `.filepawl.toml`) if hand-edits recur.
- PyPI publication.
- A JavaScript built-in mover.
