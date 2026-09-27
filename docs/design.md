# filepawl — design

## 1. Purpose

Three repositories (HQPTuner, Gauntlet, Trivia Judge) each carry a hand-rolled copy of one Python script: a file-length cap plus a one-way ratchet on files above a watch line. The copies share a core and have drifted at the edges (`CAP_EXEMPT`, `--check`, `git ls-files` default, per-entry comments, JS/CSS coverage). Every fix is made three times. The ratchet state (`ALLOWANCE`, `CAP_EXEMPT`) lives inside the script, so an engine fix must be hand-merged around per-repository state.

filepawl extracts the engine into one installable package with:

- a CLI, so agents mutate ratchet state through commands rather than editing a table by hand;
- policy separated from state;
- a second gate against flat directory structure (files per directory, cap only);
- a third gate against splits that leave a shell behind (re-export modules and trivial forwarders);
- a fourth gate against functions that nest blocks too deep;
- a fifth gate against functions whose returned dict literals disagree on their keys;
- a sixth gate against functions that return a mapping without naming its shape;
- a seventh gate against functions that return from an exception handler;
- an eighth gate against tests that assert only an absent value;
- seven test-suite gates against tests that reach private names, patch or mock the repository's own code, read the host environment, compare against a golden dump, carry a name that states no behavior, or assert only that something exists, and against fakes that compute their replies with the repository's own code;
- a `mv` command that moves a file and rewrites imports, with pluggable per-language backends;
- gate and mover registries so users can add their own;
- a Claude Code plugin whose hook tells an agent, at each edit, where the edit leaves the file against the watch line, its allowance and the cap, and stops an edit that grows a file over its cap.

Out of scope: Trivia Judge's suite-time ratchet (`check_suite_time.py`), PyPI publication, and a gate that a new test fails against the code before the change: that needs the test runner, and every gate here reads source.

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
| Barrels gate | built-in, enabled by default, Python only (`ast`); rules not widened |
| Barrels file set | tree files matched by the gate's own `include`, minus test paths; whole tree every run |
| Barrels forwarder scope | `forwarders` globs, default every checked file; a repository with thin adapter layers narrows it |
| Barrels exemptions | live in policy, human-edited, with a reason; no command writes them, and a stale one fails |
| Nesting gate | built-in, enabled by default, Python only (`ast`); rules ported unwidened from the three `nesting` scripts |
| Nesting file set | tree files matched by the gate's own `include`, test paths included; whole tree every run |
| Nesting limit | `max_depth`, default 4, the limit all three scripts hold |
| Nesting exemptions | live in policy, per function, human-edited, with a reason; no command writes them, and a stale one fails |
| Returns gate | built-in, enabled by default, Python only (`ast`); compares the key sets of a function's dict-literal returns |
| Returns file set | tree files matched by the gate's own `include`, minus test paths; whole tree every run |
| Returns shapes | only dict literals whose every key is a string constant; a literal with `**` or any other key is skipped, and a return that is not a dict literal is ignored |
| Returns exemptions | live in policy, per function, human-edited, with a reason; no command writes them, and a stale one fails |
| Named-results gate | built-in, enabled by default, Python only (`ast`); fails a return annotation or module-level alias that names a mapping with an `Any` or `object` value type, or a mapping on its own |
| Named-results file set | tree files matched by the gate's own `include` and by no `exclude` glob, minus test paths; whole tree every run |
| Named-results exemptions | none; a path leaves scope only through `exclude`, and no alias is sanctioned, parsed JSON included |
| Handlers gate | built-in, enabled by default, Python only (`ast`); fails a `return` in an `except` or `except*` handler that hands the caller a value, and a handler assignment to a name a value return reads |
| Handlers file set | tree files matched by the gate's own `include`, minus test paths; whole tree every run |
| Handlers values | `return <expr>` is a value return, `return None` included; a bare `return` fails only in a function that has a value return |
| Handlers exemptions | live in policy, per function, human-edited, with a reason; no command writes them, and a stale one fails |
| Absence gate | built-in, enabled by default, Python only (`ast`); fails a test whose every `assert` compares against an absent value and which asserts nothing else |
| Absence file set | tree files matched by the gate's own `include` and by a `tests` glob; test paths only; whole tree every run |
| Absence pairing | none; a test carries its own contrast, and a sibling test asserting a present value does not excuse it |
| Absence exemptions | live in policy, per test, human-edited, with a reason; no command writes them, and a stale one fails |
| Own code | `[tool.filepawl] packages` names the repository's top-level import names; absent, they are derived from the tree's non-test Python files |
| Test-suite gates | built-in, enabled by default, Python only (`ast`): private, mocks, environment, snapshots, test names, existence, fakes; each reads test paths only, whole tree every run |
| Test-suite site gates | private, mocks, environment, snapshots and fakes report each offending site under its innermost function, and exempt per function, human-edited, with a reason; no command writes them, and a stale one fails |
| Test-suite test gates | test names and existence judge each test as §6.11 does, and exempt per test, human-edited, with a reason; no command writes them, and a stale one fails |
| Test-suite heuristics | snapshots fails a literal over `max_items` leaves, default 8; test names fails under `min_words` words, default 3; both are policy |
| Edit-time notice | `filepawl hook` reads a Claude Code `PreToolUse` payload; it denies an edit that grows a file to over its cap, and warns on any other edit that leaves the file over the watch line or a cap |
| Plugin | a Claude Code marketplace in this repository with one plugin under `plugin/`; its hook runs the consumer's installed `filepawl`, not a bundled copy |

Rationale for cap-only directory gate: the ratchet exists to stop files parking against the cap because trimming two lines is always cheaper than splitting. Moving a file into a subpackage is cheap (tool-assisted import rewrite), so the crawl dynamic does not apply to directories.

## 3. Package layout

```
filepawl/
  __init__.py
  cli.py            # argparse: check, accept, init, mv
  cli_mv.py         # the mv command: language block, mover, stale refs, state
  hook.py           # the hook command: edit-time notice (§7.1)
  config.py         # load [tool.filepawl], merge defaults, validate
  config_values.py  # typed value checks shared by every policy table
  config_suite.py   # policy tables of the test-suite gates
  policy_stub.py    # the commented default policy block `init` writes
  state.py          # read/write .filepawl.toml
  tree.py           # git ls-files, include globs, test-path classification
  gates/
    __init__.py
    base.py         # Gate protocol, Finding dataclass
    length.py       # cap + ratchet
    dircount.py     # files-per-directory cap
    barrels.py      # re-export modules and trivial forwarders
    nesting.py      # block depth per function
    returns.py      # key sets of dict-literal returns per function
    named_results.py  # mappings of unnamed shape in return annotations and aliases
    handlers.py     # returns from exception handlers per function
    registry.py     # built-ins + entry points
    suite/
      __init__.py
      common.py     # own code, own bindings, sites, tests, exemption audit
      absence.py    # tests that assert only an absent value
      private.py    # tests that reach private names
      mocks.py      # tests that patch or mock own code
      environment.py  # tests that read the host environment
      snapshots.py  # tests that compare against a golden dump
      naming.py     # test names that state no behavior
      existence.py  # tests that assert only that something exists
      fakes.py      # fakes that compute replies with own code
  movers/
    __init__.py
    base.py         # Mover protocol, shared stale-reference grep
    rope_mover.py   # optional extra [mv]
    git_mover.py    # plain `git mv`, the default for a block with no mover
    command.py      # {old}/{new} shell template
    registry.py
tests/
.claude-plugin/
  marketplace.json  # this repository as a Claude Code marketplace
plugin/
  .claude-plugin/
    plugin.json
  hooks/
    hooks.json      # PreToolUse on Write, Edit, MultiEdit
    filepawl-hook.sh  # finds the installed filepawl, runs `filepawl hook`
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
# packages = ["mypkg"]  # own code; derived from the tree when absent (§6.12)

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

[tool.filepawl.returns]
include = ["**/*.py"]

[tool.filepawl.returns.exempt]
# "path::qualified.name" = reason. Human-edited. A function whose dict returns differ on purpose.

[tool.filepawl.named_results]
include = ["**/*.py"]
exclude = []

[tool.filepawl.handlers]
include = ["**/*.py"]

[tool.filepawl.handlers.exempt]
# "path::qualified.name" = reason. Human-edited. A function that returns from a handler on purpose.

[tool.filepawl.absence]
include = ["**/*.py"]

[tool.filepawl.absence.exempt]
# "path::qualified.name" = reason. Human-edited. A test that asserts only an absent value on purpose.

[tool.filepawl.private]
include = ["**/*.py"]

[tool.filepawl.private.exempt]
# "path::qualified.name" = reason. Human-edited. A function that reaches a private name on purpose.

[tool.filepawl.mocks]
include = ["**/*.py"]

[tool.filepawl.mocks.exempt]
# "path::qualified.name" = reason. Human-edited. A function that patches own code on purpose.

[tool.filepawl.environment]
include = ["**/*.py"]

[tool.filepawl.environment.exempt]
# "path::qualified.name" = reason. Human-edited. A function that reads the host environment on purpose.

[tool.filepawl.snapshots]
include = ["**/*.py"]
max_items = 8

[tool.filepawl.snapshots.exempt]
# "path::qualified.name" = reason. Human-edited. A function that compares against a dump on purpose.

[tool.filepawl.test_names]
include = ["**/*.py"]
min_words = 3

[tool.filepawl.test_names.exempt]
# "path::qualified.name" = reason. Human-edited. A test whose name is right as it stands.

[tool.filepawl.existence]
include = ["**/*.py"]

[tool.filepawl.existence.exempt]
# "path::qualified.name" = reason. Human-edited. A test whose contract is existence.

[tool.filepawl.fakes]
include = ["**/*.py"]

[tool.filepawl.fakes.exempt]
# "path::qualified.name" = reason. Human-edited. A fake that calls own code on purpose.

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

`filepawl check` with no paths scans `git ls-files` filtered through every language's `include` globs. Paths on argv narrow the length gate's measured set only. The stale audit, the directory gate, the barrels gate, the nesting gate, the returns gate, the named-results gate, the handlers gate and the test-suite gates always run over the whole tree, because a directory count over a subset is meaningless and an exemption audit over a subset calls live entries stale.

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

The rules are not widened. A forwarder that passes an argument by keyword and one whose chain is rooted in a call (`self.require_http().restore(x)`) are not caught. Catching them cost more false positives than the hits were worth, and review catches them.

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

### 6.8 Returns gate

A function that returns a dict literal on one path and a dict literal with other keys on another hands its caller a shape the caller must probe with `.get` or `in`. The caller cannot tell a missing key from a bug. The shape is a type the function never declared, and the fix is to return one shape, or a dataclass, or to split the function.

Checked files: tree files matched by `[tool.filepawl.returns] include`, minus test paths, since test helpers build fixtures of varying shape on purpose. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

A shaped return is a `return` statement whose value is a dict literal in which every key is a string constant. Its shape is the set of those keys; order and repeats do not count, and `return {}` has the empty shape. A dict literal with a `**` spread or with any key that is not a string constant has no knowable shape and is skipped. A `return` whose value is anything other than a dict literal is ignored, as is a bare `return`, so a function may return a shaped dict on one path and `None` on another.

Returns belong to the innermost function that contains them. A nested `def` has its own returns and does not add to the outer function's; a `lambda` has no `return` statement. Functions are named by qualified name as in §6.7.

A function whose shaped returns carry more than one shape fails. Finding: `path::qualified.name: returns dicts of N shapes ({a, b}; {a}) — return one shape`, where N counts the distinct shapes and each is listed with its keys sorted, in order of first appearance, `{}` for the empty shape.

Exemptions live in `[tool.filepawl.returns.exempt]`, keyed `path::qualified.name`, with a reason. An entry covers every function its key names. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- an entry naming no function in its file: `names no function`;
- an entry whose functions each return at most one shape: `returns one shape, so it needs no exemption`.

No returns finding is fixable by `accept`, and `accept` leaves state unchanged.

### 6.9 Named-results gate

A function annotated `-> dict[str, Any]` returns a record without naming its fields. Its caller learns the keys by reading the function body, the type checker checks none of them, and a misspelled key is a runtime `KeyError`. An alias such as `Wire = dict[str, Any]` gives the same record a name without giving it a shape. The fix is to name the shape: a dataclass, a `TypedDict`, or a precise value type.

Checked files: tree files matched by `[tool.filepawl.named_results] include` and by no `exclude` glob, minus test paths, since test helpers build payload fixtures on purpose. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

A mapping name is `dict`, `Dict`, `Mapping` or `MutableMapping`, and a loose type is `Any` or `object`. Each is recognised written bare or as the last part of an attribute chain, as in `typing.Dict` or `collections.abc.Mapping`. An annotation is loose when, anywhere in it:

- a mapping name stands on its own, not subscripted, as in `-> dict` or `-> Mapping`;
- a mapping name is subscripted and its value type, the last subscript item, is a loose type, or is a `|` union, `Optional[...]` or `Union[...]` with a loose type among its members at any depth.

Anywhere means every part of the annotation: both sides of `|`, the items of `Optional`, `Union`, `list`, `tuple`, `Callable` and every other subscript, and a string constant, which is parsed as an annotation and read the same way. The items of `Literal[...]` are values, not annotations, and are not read. So `dict[str, Any] | None`, `list[Mapping[str, object]]`, `"dict[str, Any]"`, `dict[str, Any | None]` and `dict[str, dict[str, Any]]` are loose, and `dict[str, int]` and `dict[str, list[Any]]` are not, the last because its value type is a list.

A function, at any nesting depth and named by qualified name as in §6.7, whose return annotation is loose fails. Finding: `path::qualified.name: returns an unnamed mapping (<annotation>) — name its shape`.

A module-level alias whose value is loose fails. Module level means outside every function and class, including inside a module-level `if`, `try` or `with`, so an alias under `if TYPE_CHECKING:` is checked. An alias is any of:

- `X = value`, where each plain-name target is an alias and the value is a subscript, a `|` expression, a name or an attribute chain; a call, a string or any other value is not a type and is not read;
- `X: TypeAlias = value`, with `TypeAlias` bare or as the last part of an attribute chain, where a string value is read as an annotation;
- `type X = value`.

Finding: `path::X: aliases an unnamed mapping (<value>) — name its shape`. The annotation or value is printed as `ast.unparse` spells it.

There is no exemption table. Parsed JSON gets no exception: code that passes JSON through names it with a recursive alias whose members are all concrete, `JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]`, which has no loose type in it and passes. A path leaves scope only through `exclude`.

No named-results finding is fixable by `accept`, and `accept` leaves state unchanged.
### 6.10 Handlers gate

A `return` inside an exception handler turns the exception into a value. The caller receives `None`, `False` or an empty result where an error was, and must know to test for it. The exception's type and traceback are gone, and a caller that does not test carries the sentinel on as data. The fix is to let the exception propagate, to raise a narrower one, or to handle it completely, so that nothing the function returns stands for the failure. Assigning the sentinel in the handler to a name the function returns later fails the same way. Handing it back by a route the gate does not trace passes the gate and fixes nothing.

Checked files: tree files matched by `[tool.filepawl.handlers] include`, minus test paths, since test helpers catch and return on purpose. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

A handler return is a `return` statement anywhere in the body of an `except` or `except*` handler, at any depth of blocks inside that body, including the `try`, `else` and `finally` of a `try` nested in the handler. A value return is `return <expr>`, whatever the expression, so `return None` is a value return. A bare `return` is not.

Returns belong to the innermost function that contains them, as in §6.8. A nested `def` inside a handler is judged on its own: its returns are not the outer function's handler returns, and its value returns do not count toward the outer function. A `lambda` has no `return` statement and is judged on its own, so a `lambda` does not give the outer function a value return. Functions are named by qualified name as in §6.7.

A handler assignment is an `=`, annotated `=` with a value, or augmented assignment such as `+=`, standing where a handler return would count. It binds each plain name in its targets, including names inside tuple, list and starred targets; an attribute or subscript target binds no name. Handler assignments belong to the innermost function as returns do, and one in the body of a class inside a handler binds nothing for the function. A value return reads every name loaded anywhere in its expression. Only a direct read counts: a name that reaches the return through another name or a container is not traced.

A function fails when it has a handler return that is a value return, a bare handler return while it also has a value return anywhere outside its nested functions, or a handler assignment binding a name that one of its value returns reads. Finding: `path::qualified.name: hands the caller a value from an except handler at line N — let it propagate, raise a narrower one, or handle it so nothing returned stands for the failure`, with `lines N, M` listing every failing handler return and handler assignment in source order when there is more than one.

Exemptions live in `[tool.filepawl.handlers.exempt]`, keyed `path::qualified.name`, with a reason. An entry covers every function its key names. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- an entry naming no function in its file: `names no function`;
- an entry whose functions have no failing handler return or handler assignment: `hands the caller no value from a handler, so it needs no exemption`.

No handlers finding is fixable by `accept`, and `accept` leaves state unchanged.

### 6.11 Absence gate

A test whose only claim is that something is absent — an empty list of findings, `None`, `False`, exit status 0, nothing printed — passes against code that never ran the feature, because a feature that does nothing produces exactly that. The test pins presence of the call, not behavior. The fix is to assert the absence beside a case where the feature acts, in the same test: compare the pair, as in `(run(clean), run(dirty)) == ([], [finding])`, or add an assertion of a present value on the same surface.

Checked files: tree files matched by `[tool.filepawl.absence] include` and by a `tests` glob. This gate reads test paths only. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

A test is a module-level function or async function whose name starts with `test`, or such a method directly in a module-level class whose name starts with `Test`. Tests are named by qualified name as in §6.7, so a method is `Class.test_name`.

A test's assertions are the `assert` statements in its body at any depth of blocks. An `assert` inside a nested `def`, `lambda` or class is not the test's. The test asserts something else when it holds a `with` item whose context expression calls an attribute named `raises`, `warns` or `deprecated_call`, or any call to an attribute whose name starts with `assert`, such as `self.assertEqual` or `mock.assert_called_once_with`. The gate does not read inside those.

An absent value is the constant `None`, `False`, `0`, `0.0`, `""` or `b""`; an empty list or dict display; a tuple display whose every element is an absent value, the empty tuple included; or a call to `list`, `dict`, `set`, `tuple`, `frozenset`, `str` or `bytes` with no arguments. `True` and every other constant are present values.

An absence assertion is an `assert` whose test is `not <expr>`, or a single comparison with `==` or `is` that has an absent value on either side. So `assert findings == []`, `assert out == ""`, `assert result is None`, `assert len(hits) == 0`, `assert main(["check"]) == 0` and `assert (proc.returncode, proc.stderr) == (0, "")` are absence assertions, and `assert findings == [expected]`, `assert (clean, dirty) == ([], [finding])`, `assert x is not None` and `assert "text" in out` are not.

A test fails when it has at least one `assert`, every `assert` it has is an absence assertion, and it asserts nothing else. A test with no `assert` is not this gate's to judge. A sibling test that asserts a present value on the same surface does not excuse it: the gate reads each test on its own. Finding: `path::qualified.name: asserts only an absent value — code that never ran the feature passes it too; assert it beside a case where the feature acts`.

Exemptions live in `[tool.filepawl.absence.exempt]`, keyed `path::qualified.name`, with a reason. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- an entry naming no test in its file: `names no test`;
- an entry whose test does not fail: `asserts a present value, so it needs no exemption`.

No absence finding is fixable by `accept`, and `accept` leaves state unchanged.

### 6.12 Test-suite gates, shared rules

The absence gate and the seven gates after it read a repository's tests for shapes that pass whatever the code does. They share the rules in this section.

Checked files: tree files matched by the gate's own `include` and by a `tests` glob, as in §6.11. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

Own code is the set of top-level import names listed in `[tool.filepawl] packages`. When the key is absent, the set is derived from the tree: for each tree file ending `.py` that is not a test path, a leading `src/` segment is dropped, and the name is the first remaining segment, or the file's name without `.py` when one segment remains. `packages = []` declares that the repository has no own code.

An own binding is a name that an import statement anywhere in the checked file binds to own code: `import p` and `import p.m` bind `p`, `import p.m as a` binds `a`, and `from p.m import x as y` binds `y`, where `p` is an own name. A relative import binds no own name, since a test file's relative imports reach other test modules. An expression is own-rooted when it is an own binding or an attribute chain whose root is one. A dotted string is own when its first dotted segment is an own name.

Standard names are resolved through the checked file's imports: `import os` makes `os.getcwd` read as `os.getcwd`, `from os import getcwd` makes `getcwd` read as `os.getcwd`, and `from pathlib import Path` makes `Path.cwd` read as `pathlib.Path.cwd`. An expression's dotted name is its attribute chain with its root so resolved; a root no import binds stands for itself.

A site gate reports sites. A site belongs to the innermost function that contains it, named by qualified name as in §6.7, or to `<module>` when no function contains it; a `lambda` is part of its enclosing function. A unit with sites fails once. Finding: `path::unit: <what> at line N — <fix>`, with `lines N, M` listing every site in source order when there is more than one. Exemptions live in `[tool.filepawl.<gate>.exempt]`, keyed `path::unit`, with a reason. The audit covers every entry on every run and reports each finding under path `pyproject.toml`: an entry whose path is not a checked file, `names no file`; an entry naming no function in its file, `names no function`; an entry whose unit has no site, the gate's own `so it needs no exemption` message.

A test gate judges tests, as §6.11 defines them, and reports each failing test once, exempted and audited as §6.11 does with its own messages.

A consumer adopting these gates decides their findings per repository, as it does directory-gate findings, and sets `packages` when the tree does not show its own code.

No test-suite finding is fixable by `accept`, and `accept` leaves state unchanged.

### 6.13 Private gate

A test that reads a private attribute or imports a private name pins the layout of the code instead of its behavior. A refactor that keeps every behavior breaks it, and a test broken by a refactor has found a defect in itself.

A site gate. A private name begins with `_` and is not a dunder, one that begins and ends with `__`. A name is the file's own when the checked file defines it: as a function or class name, as a plain assignment target, or as the attribute of an attribute assignment target on any object. The named-tuple members `_asdict`, `_replace`, `_fields`, `_field_defaults` and `_make` are public API and are never private. A site is:

- an attribute read or written, `x._name`, whose name is private and not the file's own, unless `x` is the plain name `self` or `cls`;
- a call to the builtin `getattr`, `setattr`, `delattr` or `hasattr` whose second argument is a string constant naming a private name that is not the file's own;
- an import of own code whose module path has a private segment or which imports a private name, as in `import p._m`, `from p._m import x` and `from p.m import _x`.

A failing unit is reported as `path::unit: reaches _a, _b at line N — test through the public surface`, the private names listed once each in order of first appearance, and an exemption that excuses nothing as `reaches no private name, so it needs no exemption`.

### 6.14 Mocks gate

A test that replaces the repository's own function with a stub tests the stub. The code under test is exercised against a collaborator that behaves as the test writer believed, not as it does. The fix is a fake at the wire: a fake server speaking the real protocol, a fake file tree, a fake subprocess the test writes.

A site gate. A site is:

- a call to `patch`, or to an attribute chain whose last name is `patch`, whose first argument is an own dotted string;
- a call to `object`, `dict` or `multiple` on such a chain, as in `patch.object` or `mocker.patch.dict`, whose first argument is own-rooted or an own dotted string;
- a call to an attribute named `setattr`, `delattr`, `setitem` or `delitem`, the `monkeypatch` forms, whose first argument is own-rooted, or for `setattr` and `delattr` an own dotted string;
- a call to the builtin `setattr` or `delattr` whose first argument is own-rooted;
- an assignment or `del` whose target is an attribute chain rooted at an own binding, as in `engine.fetch = fake_fetch`;
- a call to `Mock`, `MagicMock`, `AsyncMock`, `NonCallableMock` or `NonCallableMagicMock`, bare or as the last name of a chain, with a `spec` or `spec_set` keyword that is own-rooted, and a call to `create_autospec` whose first argument is own-rooted.

Patching a module table or import path to load the unit under test, as in `monkeypatch.setitem(sys.modules, ...)`, is not a site: its first argument is not own code. A failing unit is reported as `path::unit: patches own code at line N — fake at the wire, never over the code`, and an exemption that excuses nothing as `patches no own code, so it needs no exemption`.

### 6.15 Environment gate

A test that reads the host's name, working directory, home, environment variables, locale or time zone, or binds a fixed port, is green on one machine and red on another. The fix is to hand the code the value it needs, through an argument, a fixture that sets it, or a port of 0.

A site gate. A site is, by dotted name as §6.12 resolves it:

- a call to `socket.gethostname`, `socket.getfqdn`, `platform.node`, `platform.uname` or `os.uname`;
- a call to `os.getcwd`, `os.getcwdb` or `pathlib.Path.cwd`;
- a call to `pathlib.Path.home` or `os.path.expanduser`, or to any attribute named `expanduser`;
- any `os.environ` or `os.environb`, and a call to `os.getenv` or `os.getenvb`, except `os.environ` or `os.environb` as the first argument of a call to an attribute named `setitem` or `delitem`, or to `patch.dict` on any chain, which scope a change to the test;
- a call to any function of `locale`;
- any `time.tzname`, `time.timezone`, `time.altzone` or `time.daylight`, a call to `time.localtime`, `time.mktime` or `time.ctime`, and a call to an attribute named `astimezone` with no arguments;
- a call to a name or attribute named `bind`, `connect`, `connect_ex`, `create_connection`, `create_server`, `open_connection` or `start_server`, or whose name ends in `Server` or `Connection`, whose port is an integer constant from 1 to 65535: the second element of a tuple display passed first, the second positional argument, or the `port` keyword.

A failing unit is reported as `path::unit: reads the host environment at line N — hand the code the value it needs`, and an exemption that excuses nothing as `reads no host environment, so it needs no exemption`.

### 6.16 Snapshots gate

A test that compares a whole structure against a stored or written-out copy re-asserts the implementation back at itself. Every harmless change breaks it, the fix is to regenerate the copy, and a regenerated copy has checked nothing. The fix is to compare the fields with known meaning.

A site gate. A site is an `assert` whose test is a single comparison with `==`, either side of which is a dump:

- a dict, list, tuple or set display holding more than `max_items` leaves, default 8: an element that is not a display is one leaf, an empty display is one leaf, a dict's values are counted and its keys are not, and a nested display counts its own leaves;
- a file read of a golden file: an expression containing a call to `open`, or to an attribute named `read_text` or `read_bytes`, whose arguments or receiver mention `__file__`, `importlib.resources` or a module-level name whose value mentions `__file__`;
- a plain name that the same function assigns, anywhere before the `assert`, a value holding such a file read;
- the name `snapshot` or an expression rooted at it, the fixture of snapshot libraries.

A file the test's own run wrote, read back from a temporary directory, is not a golden file. A failing unit is reported as `path::unit: compares against a dump at line N — assert the fields with known meaning`, and an exemption that excuses nothing as `compares against no dump, so it needs no exemption`.

### 6.17 Test-names gate

A test's name is the report its failure files. `test_parse_2` says which function failed, not what broke. The fix is to name the behavior, as in `test_checked_checkbox_parses_true`.

A test gate. A test's words are the parts of its name after the leading `test`, split on `_`, empty parts dropped, and for a method the words of its class name after the leading `Test`, split on `_` and before each capital letter that follows a lower-case letter or digit. A test fails when it has fewer than `min_words` words, default 3, or when its last word is all digits. A failing test is reported as `path::qualified.name: names no behavior — state what the code does, in at least M words, with no number at the end`, and an exemption that excuses nothing as `names a behavior, so it needs no exemption`.

### 6.18 Existence gate

A test whose only claim is that a value exists, not what it is, passes against a stub that returns any value. It pins presence of the result, not behavior. The fix is to assert the value.

A test gate. An existence assertion is an `assert` whose test is:

- a bare name, attribute or subscript, read for its truth;
- a call to `isinstance`, `issubclass`, `callable`, `hasattr`, `bool` or `len`;
- a single comparison with `is not` or `!=` that has an absent value (§6.11) on either side;
- a single comparison `> 0` or `>= 1`, or mirrored, `0 <` or `1 <=`, against any expression;
- a single `in` comparison whose right side is a call to an attribute named `keys`, or to `vars` or `dir`.

A test fails when it has at least one `assert`, every `assert` it has is an existence assertion or an absence assertion (§6.11), at least one is an existence assertion, and it asserts nothing else, as §6.11 defines asserting something else. A test whose every `assert` is an absence assertion is the absence gate's. A failing test is reported as `path::qualified.name: asserts only that a value exists — a stub returning any value passes it too; assert the value`, and an exemption that excuses nothing as `asserts a value, so it needs no exemption`.

### 6.19 Fakes gate

A fake that works out its reply by calling the code under test is a second copy of that code, wrong together with the first. The fix is a table: the test writes what the fake answers.

A site gate. A fake is a function or class whose name, leading underscores dropped, starts with `fake` or `Fake`, and every function and class in a checked file whose name starts with `fake`. A site is a call, anywhere inside a fake, whose callee is own-rooted and whose last name starts with a lower-case letter or `_`. Constructing an own class, a callee whose last name starts with a capital, is not a site: a fake builds its reply out of own types. A failing unit is reported as `path::unit: computes a reply with own code at line N — answer from a table the test writes`, and an exemption that excuses nothing as `calls no own code, so it needs no exemption`.

## 7. CLI

```
filepawl check [PATH...]
filepawl accept [PATH...] [--reason TEXT]
filepawl init
filepawl mv OLD NEW
filepawl hook
```

- `check`: section 6.
- `accept`: for each watched non-test file (all of them when no path given): add a missing entry at current length, lower an entry whose file shrank, drop stale entries. Refuses to raise an entry: a file that grew prints the same "grew past allowance; split it" finding and exits 1. `--reason` with exactly one path sets that entry's reason.
- `init`: write `.filepawl.toml` from the current tree (equivalent to `accept` on empty state) and, if `[tool.filepawl]` is absent, append a commented default policy block to `pyproject.toml`. Refuses to overwrite an existing state file.
- `mv`: section 8.
- `hook`: section 7.1.

### 7.1 Edit-time notice

The length gate fails at commit time. An agent that learns only then that a file must be split has already spent a session growing it, and does the split with the whole session in context. A split is mechanical work that a cheaper agent can do from a short brief, if the need for it is known early. `filepawl hook` makes it known at the first edit.

`filepawl hook` reads one Claude Code `PreToolUse` payload as JSON on stdin. It acts on `Write`, `Edit` and `MultiEdit`; any other tool is ignored. It resolves the repository from the payload's `cwd`, loads policy and state, and takes `tool_input.file_path` relative to the repository root. It then projects the file's length after the edit, measured as in §6.1:

- `Write`: the lines of `content`.
- `Edit`: the file's text with `old_string` replaced by `new_string`, once, or everywhere when `replace_all` is true.
- `MultiEdit`: each entry of `edits` applied in order the same way.

The file need not be tracked: a `Write` that creates a file is projected like any other. A path matched by no language `include` is ignored, as is any path when the length gate is disabled.

An edit is denied when the projected length B is over the file's cap (`cap_tests` for a test path, `cap` otherwise), the path is not exempt, and B exceeds A, the length before the edit. The reason reads `path: this edit takes it A → B lines, over cap C; blocked. Split the file first; the split is mechanical and can be delegated.`

Otherwise a notice is emitted when the projected length puts the file in the ratchet or over a cap:

- Test path, not exempt, over `cap_tests`: `path: test file goes A → B lines, over cap C_T; split it before committing.`
- Non-test path over `watch` with an allowance entry: `path: in the length ratchet at N lines; this edit takes it A → B.` followed by `B − N lines over the allowance; split them out before committing.` when B exceeds N, and otherwise `It may shrink, never grow past N.`
- Non-test path over `watch` with no entry: `path: goes A → B lines, over watch line W; it enters the length ratchet on the next \`filepawl accept\` and may only shrink after that.`
- Either non-test case, when B exceeds `cap` and the path is not exempt, adds `Over cap C; split it before committing.`
- Every non-test notice ends `Plan the split now; it is mechanical and can be delegated.`

A is 0 for a file that does not exist, so a `Write` that creates a file over its cap is denied. The notice goes to stdout as `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "filepawl: <notice>"}}` and a denial as `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "filepawl: <reason>"}}`. Neither means no output.

The cap is a hard gate at commit, so denying growth past it moves that failure to the edit that causes it. The ratchet band only warns: a split in progress passes through states the ratchet would fail, such as a function present in both the old and the new module, and denying those writes would block the split itself. A split never needs to grow a file over its cap, because the new modules start empty and the original only shrinks. An edit that leaves an over-cap file over its cap but no longer is let through with a notice, so a file already over its cap after adoption or a lowered cap can be split a piece at a time. Every outcome exits 0: a malformed payload, a directory outside any repository, a policy or state error, an unreadable file, and an `old_string` that does not occur are all silent. `check` reports the configuration errors, and Claude Code reports the failed edit.

The plugin under `plugin/` wires this hook for `Write|Edit|MultiEdit`. Its script runs `$CLAUDE_PROJECT_DIR/.venv/bin/filepawl hook` when that file is executable, otherwise `filepawl hook` from `PATH`, and exits 0 silently when neither exists, so the notice always comes from the consumer's pinned filepawl. The script exits 0 whatever filepawl returns, because a `PreToolUse` hook exiting 2 blocks the edit.

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
- Returns gate: one shape passes; two shapes fail and are listed in first-appearance order; key order and repeats do not count; `{}` is a shape; spread and non-string-constant keys are skipped; non-dict and bare returns are ignored; a nested `def`'s returns are its own; methods are named by qualified name; test paths and files outside `include` are not checked; a file that does not parse is skipped; exemption and each audit message.
- Named-results gate: each mapping name, bare and subscripted, with `Any` and with `object`, bare and attribute-qualified; a precise value type passes; a loose type inside a value-type union fails and inside a value-type `list` passes; a loose mapping inside `|`, `Optional`, `list`, `tuple`, `Callable`, a nested mapping and a quoted annotation fails; `Literal` items are not read; async functions, nested functions and methods named by qualified name; each alias form, including under `if TYPE_CHECKING:`; a call or string assignment is not an alias; a class-level or function-level alias is not checked; `exclude`, test paths and files outside `include` are not checked; a file that does not parse is skipped.
- Handlers gate: `return <expr>` and `return None` in `except` and `except*` fail; a bare `return` in a handler passes alone and fails beside a value return, including a `return None`; a return deep in blocks inside a handler counts, and one in `try`, `else` or `finally` outside a handler does not; a nested `def` in a handler is judged on its own, and its value returns do not count toward the outer function; a `lambda` gives the outer function no value return; a name bound in a handler by `=`, annotated or augmented assignment, including inside tuple, list and starred targets, fails when a value return reads it anywhere in its expression, and passes when no value return reads it; attribute and subscript targets bind no name; a handler assignment deep in blocks counts, and one in a nested `def` or class body does not; several failing returns and assignments are listed by line in source order; methods are named by qualified name; test paths and files outside `include` are not checked; a file that does not parse is skipped; exemption and each audit message.
- Absence gate: each absent value, as either side of `==` and `is`, fails alone; `not <expr>` and `len(...) == 0` fail; a tuple of absent values fails and a tuple holding one present value passes; `True`, a non-empty display and a call with arguments are present values; `!=`, `is not`, `in` and a bare expression pass; a test with one present assertion among absent ones passes; `pytest.raises`, `pytest.warns` and an `assert*` method call count as asserting something else; a test with no `assert` passes; an `assert` in a nested `def` is not the test's; `Test` class methods are named by qualified name and methods of other classes are not tests; non-test paths and files outside `include` are not checked; a file that does not parse is skipped; exemption and each audit message.
- Own code: derived from the tree's non-test Python files, root modules and `src/` layout included; `packages` replaces the derived set, and `packages = []` leaves none.
- Private gate: a private attribute read and write, a builtin `getattr` family call, a private module segment and a private imported name each fail; `self` and `cls` receivers, dunders, named-tuple members and names the file defines pass; a third-party private import passes; sites at module level report under `<module>`; several sites list their names and lines; exemption and each audit message.
- Mocks gate: each patch form with an own target fails and with a third-party target passes; `monkeypatch.setattr` in its string and object forms; `sys.modules` patching passes; attribute assignment and `del` on an own binding fail; `Mock` with an own `spec` and `create_autospec` of own code fail; a relative import binds no own name; exemption and each audit message.
- Environment gate: each named call and read fails, reached through `import x`, `from x import y` and an alias; `os.environ` inside `setitem`, `delitem` and `patch.dict` passes; `astimezone` with an argument passes; each port form fails at a fixed port and passes at 0; exemption and each audit message.
- Snapshots gate: a display at `max_items` leaves passes and one over fails; dict keys do not count; a golden read through `__file__` directly, through a module-level name and through a local name fails; a read of a temporary file passes; `snapshot` fails; `!=` is not read; exemption and each audit message.
- Test-names gate: fewer than `min_words` words fails; a trailing number fails; a class name's words count for a method; exemption and each audit message.
- Existence gate: each existence form fails alone and beside absence assertions; an existence assertion beside a value assertion passes; all-absence tests are left to the absence gate; `pytest.raises` counts as asserting something else; exemption and each audit message.
- Fakes gate: a fake by name and by file name; a lower-case own callee fails and a capitalised one passes; a third-party call passes; a call outside a fake passes; exemption and each audit message.
- `accept`: adds, lowers, refuses to raise, drops stale, preserves reason, stable sort.
- `init`: fresh tree, refuses overwrite, appends policy stub once.
- `mv`: `command` backend with a fake script; `rope` backend behind `pytest.importorskip("rope")`; stale-ref grep finds a `mock.patch` string.
- Registry: an entry-point gate and mover discovered from a test-installed distribution.
- `hook`: denial of growth over `cap` and `cap_tests`, including a new file; no denial for an exempt path or an over-cap file that does not grow; each notice form; projection for `Write`, `Edit`, `replace_all` and `MultiEdit`; an untracked new file; silence under the watch line, for other tools, for paths outside every `include`, and on every error path; exit 0 throughout. The plugin script: exits 0 and prints nothing when no filepawl is found, and exits 0 when filepawl exits 2.
- Self-application: filepawl's own tree passes `filepawl check` with default policy; the repository's pre-commit runs it.

## 10. Migration of the three consumers

Per repository, one PR:

1. Add `filepawl` to dev dependencies (git URL pinned to a tag) and a pre-commit entry `repo: https://github.com/ohshitgorillas/filepawl`, `rev: vX.Y.Z`, hook `filepawl`. 2. Write `[tool.filepawl]` in `pyproject.toml` only where the repository departs from defaults: HQPTuner adds a `javascript` block and the `junkcal_fixture.py` exemption; Gauntlet adds `**/*.sh` to `include`. For the barrels gate, HQPTuner sets `include` to `hqptuner/**/*.py` and `scripts/**/*.py`, `forwarders` to its `core`, `lanes`, `presets`, `engine` and `conf` packages, and carries its two `presetops.py` forwarder exemptions over with their reasons. Trivia Judge sets `include` and `forwarders` to `triviajudge/**` and `scripts/**`. Gauntlet sets `include` to `hooks/**/*.py` and `scripts/**/*.py`. Gauntlet's script also reads untracked files, and filepawl does not. The nesting gate needs no policy in any of the three: its default `include` is the file set all three measure, and none carries a nesting exemption. The returns gate is new to all three; its findings are decided per repository, as directory-gate findings are. So is the absence gate, whose findings fall in each repository's tests. 3. Run `filepawl init`. Existing `ALLOWANCE` values need no import: the old ratchet already forced exact equality with current lengths, so `init` reproduces them. Carry Trivia Judge's per-entry comments over with `filepawl accept <path> --reason "..."`. 4. Run `filepawl check`; expect clean. Directory gate may surface new findings; those are decided per repository, not silently exempted. 5. Delete the old length, barrels and nesting scripts, their tests, and their Makefile / pre-commit / gate-runner wiring. Replace the CONTRIBUTING and CLAUDE.md prose with one line pointing at `filepawl check` and `filepawl accept`.

## 11. Open items deferred

- A plugin skill, and a plugin hook denying edits to `.filepawl.toml`, if hand-edits recur.
- PyPI publication.
- A JavaScript built-in mover.
