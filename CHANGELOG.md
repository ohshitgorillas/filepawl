# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- **The named-results gate fails a field of unnamed type.** A class field, or an attribute a method declares as `self.x: T`, typed `Any`, `object`, a union holding one, or a mapping the gate already refuses in a return annotation fails, with `ClassVar`, `Final`, `Annotated`, `InitVar`, `Required`, `NotRequired` and `ReadOnly` seen through.
- **The returns gate fails a padded key.** A function whose dict-literal returns share one key set fails when a key is `None`, an empty string or an empty collection on some of them and a value on others. The judge treats padding by a route the gate does not read as a dodge.

- **The reach gate fails a module that imports another module's private name.** A `from` import of a private name out of the repository's own code fails, relative imports and imports inside functions included; a private module, a dunder and a third-party name pass. `[tool.filepawl.reach]` takes `include`, `exempt` keyed `path::name` with a reason, and `enabled`, and the `filepawl init` stub carries the block.

### Changed

- **`filepawl check` can report named-results findings on classes, returns findings on functions of one shape, and reach findings, on trees that passed before.**

## 0.9.0 - 2026-09-26

### Added

- **`filepawl judge` fails a commit that hides a handlers or returns finding instead of fixing it.** Each dodge prints one line naming the function and the reason. `--head` checks the last commit. The judge needs the `claude` CLI, and a commit that silences no finding costs no call.
- **Consumers can turn the judge on per repository and keep chosen functions from it.** It is off until `[tool.filepawl.judge] enabled = true`; `model`, `batch` and `timeout` shape the calls, and `exempt` excuses a function with a reason.
- **A consumer can run the judge on every commit** by listing the `filepawl-judge` hook beside `filepawl`.

## 0.8.0 - 2026-09-26

### Added

- **The absence gate fails tests that assert only an absent value.** A test whose every `assert` compares against `None`, `False`, `0`, `""`, an empty list or dict, a tuple of such values or an empty constructor, or is `not <expr>`, and which asserts nothing else, fails: code that never ran the feature passes it too. Only test paths are checked.
- **The absence gate reads `[tool.filepawl.absence]` in `pyproject.toml`.** `include` narrows which test files it checks, `exempt` excuses one test keyed `path::qualified.name` with a reason, and `enabled = false` turns the gate off. An exemption naming a missing file, a missing test or a test that asserts a present value is reported as a finding.
- **The `filepawl init` stub gains the absence block.**
- **The private gate fails tests that reach a private name.** A test that reads or writes `obj._x`, names a private attribute through `getattr`, `setattr`, `patch.object` or a dotted `patch` string, or imports a private module or name of the repository's own code fails. `self` and `cls`, dunders, named-tuple members and names the test file defines pass.
- **The mocks gate fails tests that patch.** Every `patch` form, `monkeypatch.setattr` and `delattr`, `setitem` and `delitem` outside `sys.modules` and `os.environ`, assignment to an attribute of an imported name, and a `Mock` with `spec`, `spec_set` or `create_autospec` fails, whatever it replaces.
- **The clocks gate fails tests that run on the wall clock.** A real sleep on anything but `0`, a call that reads a real clock, and a duration under half a second given to `timeout`, `interval`, `delay` or a name ending in one of them fail, however the clock is imported and in every test directory.
- **`[tool.filepawl] packages` names the repository's own code.** When absent, it is derived from the tree's non-test Python files.
- **The private, mocks and clocks gates read `[tool.filepawl.private]`, `[tool.filepawl.mocks]` and `[tool.filepawl.clocks]`.** Each takes `include`, `exempt` keyed `path::qualified.name` with a reason, and `enabled`; `clocks` also takes `names`, the pacing names it reads. An exemption that excuses nothing fails. The `filepawl init` stub carries all three.

### Changed

- **`filepawl check` can report absence, private, mocks and clocks findings on test suites that passed before.**

## 0.7.0 - 2026-09-26

### Changed

- **`filepawl check` can report handlers findings on code that passed before.**

## 0.6.0 - 2026-09-26

### Added

- **The handlers gate fails functions that return from an exception handler.** A `return` with a value inside `except` or `except*` fails, `return None` included, and so does a bare `return` there when the function returns a value elsewhere.
- **The handlers gate takes a `[tool.filepawl.handlers]` policy.** `include`, `exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the handlers block.**

## 0.5.0 - 2026-09-26

### Added

- **The named-results gate fails mappings of unnamed shape in results.** A return annotation or module-level alias that names `dict`, `Dict`, `Mapping` or `MutableMapping` with an `Any` or `object` value type, or one of those names on its own, fails wherever it sits in the annotation.
- **The named-results gate takes a `[tool.filepawl.named_results]` policy.** `include`, `exclude`, `enabled`. It has no exemptions.
- **The `filepawl init` stub gains the named_results block.**

## 0.4.0 - 2026-09-25

### Added

- **The returns gate fails functions whose dict returns disagree.** A function that returns dict literals with different key sets on different paths fails.
- **The returns gate takes a `[tool.filepawl.returns]` policy.** `include`, `exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the returns block.**

## 0.3.0 - 2026-09-24

### Added

- **The Claude Code plugin checks every agent edit before it lands.** With the `filepawl` plugin installed from the marketplace, an agent is warned when its edit puts a file over the watch line or past its allowance, and blocked when the edit grows a non-exempt file over its cap.

## 0.2.0 - 2026-09-23

### Added

- **The barrels gate fails re-exports and trivial forwarders.** A re-export module is a file other than `__init__.py` that imports and defines nothing; a trivial forwarder is a function that only returns a call on its own arguments, passed by position to a call chain rooted at a name.
- **The barrels gate takes a `[tool.filepawl.barrels]` policy.** `include`, `forwarders`, `module_exempt`, `forwarder_exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the barrels block.**
- **The nesting gate fails over-deep functions.** A function that nests blocks deeper than the limit fails.
- **The nesting gate takes a `[tool.filepawl.nesting]` policy.** `include`, `max_depth`, `exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the nesting block.**

## 0.1.0 - 2026-09-21

### Added

- **The length gate holds long files to their size.** A file over the watch line cannot grow, and shrinking it lowers its limit for good.
- **The directory-count gate caps files per directory.** Per-directory file cap, with test directory handling.
- **The `check` command scans the tree.** It reports findings sorted by path, and prints the exact `filepawl accept` command when findings are fixable.
- **The `accept` command reconciles the allowance table.** It adds missing entries, lowers entries for shrunk files, drops stale entries, and preserves per-entry reason annotations.
- **The `init` command bootstraps state and policy.** It writes the `.filepawl.toml` state file from the current tree, and appends commented default policy to `pyproject.toml` if absent.
- **The `mv` command moves a file or module.** It rewrites imports, updates allowance entries, and reports stale references found in the tree.
- **Exit codes distinguish clean, findings and error.** 0 for clean, 1 for findings, 2 for configuration or state error.
- **Policy lives in `pyproject.toml`'s `[tool.filepawl]`.** Languages, tests glob, per-gate caps and settings, per-language include patterns, mover selection, exemptions from hard cap.
- **State lives in `.filepawl.toml`.** An allowance table with file paths and line counts, a per-entry reason field, and version tracking.
- **A rope mover backend moves Python modules.** It moves a module into another package under the same name and rewrites every import of it (optional `mv` extra); a move that renames the file exits 2.
- **`mv` can hand a move to a shell command instead of a built-in mover.** Set `mover_command` to a template with `{old}` and `{new}` placeholders, and filepawl shell-quotes the paths and runs it.
- **Third-party gates and movers work like built-in ones.** Register a gate under `filepawl.gates` or a mover under `filepawl.movers`, and `check` and `mv` use it.
- **filepawl runs as a pre-commit hook.** It scans the whole tree on every commit.
