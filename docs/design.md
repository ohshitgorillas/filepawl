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
- a `mv` command that moves a file and rewrites imports, with pluggable per-language backends;
- gate and mover registries so users can add their own;
- a Claude Code plugin whose hook tells an agent, at each edit, where the edit leaves the file against the watch line, its allowance and the cap, and stops an edit that grows a file over its cap.

Out of scope: Trivia Judge's suite-time ratchet (`check_suite_time.py`), PyPI publication.

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
| Handlers gate | built-in, enabled by default, Python only (`ast`); fails a `return` in an `except` or `except*` handler that hands the caller a value |
| Handlers file set | tree files matched by the gate's own `include`, minus test paths; whole tree every run |
| Handlers values | `return <expr>` is a value return, `return None` included; a bare `return` fails only in a function that has a value return |
| Handlers exemptions | live in policy, per function, human-edited, with a reason; no command writes them, and a stale one fails |
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

`filepawl check` with no paths scans `git ls-files` filtered through every language's `include` globs. Paths on argv narrow the length gate's measured set only. The stale audit, the directory gate, the barrels gate, the nesting gate, the returns gate, the named-results gate and the handlers gate always run over the whole tree, because a directory count over a subset is meaningless and an exemption audit over a subset calls live entries stale.

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

A `return` inside an exception handler turns the exception into a value. The caller receives `None`, `False` or an empty result where an error was, and must know to test for it. The exception's type and traceback are gone, and a caller that does not test carries the sentinel on as data. The fix is to let the exception propagate, to raise a narrower one, or to handle it completely, so that nothing the function returns stands for the failure. Moving the `return` out of the handler while still handing back the sentinel passes the gate and fixes nothing.

Checked files: tree files matched by `[tool.filepawl.handlers] include`, minus test paths, since test helpers catch and return on purpose. Each is parsed with `ast` from `utf-8` text. A file that does not parse is skipped, as in §6.6.

A handler return is a `return` statement anywhere in the body of an `except` or `except*` handler, at any depth of blocks inside that body, including the `try`, `else` and `finally` of a `try` nested in the handler. A value return is `return <expr>`, whatever the expression, so `return None` is a value return. A bare `return` is not.

Returns belong to the innermost function that contains them, as in §6.8. A nested `def` inside a handler is judged on its own: its returns are not the outer function's handler returns, and its value returns do not count toward the outer function. A `lambda` has no `return` statement and is judged on its own, so a `lambda` does not give the outer function a value return. Functions are named by qualified name as in §6.7.

A function fails when it has a handler return that is a value return, or a bare handler return while it also has a value return anywhere outside its nested functions. Finding: `path::qualified.name: returns from an except handler at line N — let it propagate, raise a narrower one, or handle it so nothing returned stands for the failure`, with `lines N, M` listing every failing handler return in source order when there is more than one.

Exemptions live in `[tool.filepawl.handlers.exempt]`, keyed `path::qualified.name`, with a reason. An entry covers every function its key names. The audit covers every entry on every run and reports each finding under path `pyproject.toml`:

- an entry whose path is not a checked file: `names no file`;
- an entry naming no function in its file: `names no function`;
- an entry whose functions have no failing handler return: `returns from no handler, so it needs no exemption`.

No handlers finding is fixable by `accept`, and `accept` leaves state unchanged.

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
- Handlers gate: `return <expr>` and `return None` in `except` and `except*` fail; a bare `return` in a handler passes alone and fails beside a value return, including a `return None`; a return deep in blocks inside a handler counts, and one in `try`, `else` or `finally` outside a handler does not; a nested `def` in a handler is judged on its own, and its value returns do not count toward the outer function; a `lambda` gives the outer function no value return; several failing returns are listed by line; methods are named by qualified name; test paths and files outside `include` are not checked; a file that does not parse is skipped; exemption and each audit message.
- `accept`: adds, lowers, refuses to raise, drops stale, preserves reason, stable sort.
- `init`: fresh tree, refuses overwrite, appends policy stub once.
- `mv`: `command` backend with a fake script; `rope` backend behind `pytest.importorskip("rope")`; stale-ref grep finds a `mock.patch` string.
- Registry: an entry-point gate and mover discovered from a test-installed distribution.
- `hook`: denial of growth over `cap` and `cap_tests`, including a new file; no denial for an exempt path or an over-cap file that does not grow; each notice form; projection for `Write`, `Edit`, `replace_all` and `MultiEdit`; an untracked new file; silence under the watch line, for other tools, for paths outside every `include`, and on every error path; exit 0 throughout. The plugin script: exits 0 and prints nothing when no filepawl is found, and exits 0 when filepawl exits 2.
- Self-application: filepawl's own tree passes `filepawl check` with default policy; the repository's pre-commit runs it.

## 10. Migration of the three consumers

Per repository, one PR:

1. Add `filepawl` to dev dependencies (git URL pinned to a tag) and a pre-commit entry `repo: https://github.com/ohshitgorillas/filepawl`, `rev: vX.Y.Z`, hook `filepawl`. 2. Write `[tool.filepawl]` in `pyproject.toml` only where the repository departs from defaults: HQPTuner adds a `javascript` block and the `junkcal_fixture.py` exemption; Gauntlet adds `**/*.sh` to `include`. For the barrels gate, HQPTuner sets `include` to `hqptuner/**/*.py` and `scripts/**/*.py`, `forwarders` to its `core`, `lanes`, `presets`, `engine` and `conf` packages, and carries its two `presetops.py` forwarder exemptions over with their reasons. Trivia Judge sets `include` and `forwarders` to `triviajudge/**` and `scripts/**`. Gauntlet sets `include` to `hooks/**/*.py` and `scripts/**/*.py`. Gauntlet's script also reads untracked files, and filepawl does not. The nesting gate needs no policy in any of the three: its default `include` is the file set all three measure, and none carries a nesting exemption. The returns gate is new to all three; its findings are decided per repository, as directory-gate findings are. 3. Run `filepawl init`. Existing `ALLOWANCE` values need no import: the old ratchet already forced exact equality with current lengths, so `init` reproduces them. Carry Trivia Judge's per-entry comments over with `filepawl accept <path> --reason "..."`. 4. Run `filepawl check`; expect clean. Directory gate may surface new findings; those are decided per repository, not silently exempted. 5. Delete the old length, barrels and nesting scripts, their tests, and their Makefile / pre-commit / gate-runner wiring. Replace the CONTRIBUTING and CLAUDE.md prose with one line pointing at `filepawl check` and `filepawl accept`.

## 11. Open items deferred

- A plugin skill, and a plugin hook denying edits to `.filepawl.toml`, if hand-edits recur.
- PyPI publication.
- A JavaScript built-in mover.
