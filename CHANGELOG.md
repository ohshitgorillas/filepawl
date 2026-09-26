# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

- **An edit that would overgrow a file gets flagged before it lands.** An agent is warned when its edit puts a file over the watch line or past its allowance, and blocked outright when the edit grows a non-exempt file over its cap.
- **The Claude Code plugin checks every agent edit.** Installing the `filepawl` plugin from the marketplace checks each file edit an agent makes against the length rules before it lands.

## 0.2.0 - 2026-09-23

### Added

- **The barrels gate fails re-exports and trivial forwarders.** A re-export module is a file other than `__init__.py` that imports and defines nothing; a trivial forwarder is a function that only returns a call on its own arguments.
- **The barrels gate takes a `[tool.filepawl.barrels]` policy.** `include`, `forwarders`, `module_exempt`, `forwarder_exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the barrels block.**
- **The nesting gate fails over-deep functions.** A function that nests blocks deeper than the limit fails.
- **The nesting gate takes a `[tool.filepawl.nesting]` policy.** `include`, `max_depth`, `exempt`, `enabled`. An exemption that excuses nothing fails.
- **The `filepawl init` stub gains the nesting block.**

### Known limitations

- **The barrels gate does not catch every forwarder.** A forwarder that passes an argument by keyword, or whose call chain starts with a call, passes the gate.

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
- **A rope mover backend moves Python modules.** It moves a module and rewrites every import of it (optional `mv` extra).
- **`mv` can hand a move to a shell command instead of a built-in mover.** Set `mover_command` to a template with `{old}` and `{new}` placeholders, and filepawl shell-quotes the paths and runs it.
- **Third-party gates and movers work like built-in ones.** Register a gate under `filepawl.gates` or a mover under `filepawl.movers`, and `check` and `mv` use it.
- **filepawl runs as a pre-commit hook.** It scans the whole tree on every commit.

### Known limitations

- **Excluded files still need allowance entries.** A file excluded from the build still needs an allowance entry, and a policy exemption lifts only its hard cap.
- **`mv` with the rope backend moves a module without renaming it.** Imports are rewritten to reflect the new location, but the module name itself does not change if the destination directory name differs from the package name.
