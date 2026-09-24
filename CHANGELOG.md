# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.0 - 2026-09-24

### Added

- `filepawl hook`: reads a Claude Code `PreToolUse` payload, projects the edited file's length, and tells the agent when the edit puts the file over the watch line, past its allowance or over a cap. It never blocks and always exits 0.
- Claude Code plugin marketplace with a `filepawl` plugin that runs `filepawl hook` before `Write`, `Edit` and `MultiEdit`.

## 0.2.0 - 2026-09-23

### Added

- Barrels gate: fails a re-export module (a file other than `__init__.py` that imports and defines nothing) and a trivial forwarder (a function that only returns a call on its own arguments).
- `[tool.filepawl.barrels]` policy: `include`, `forwarders`, `module_exempt`, `forwarder_exempt`, `enabled`. An exemption that excuses nothing fails.
- `filepawl init` stub includes the barrels block.
- Nesting gate: fails a function that nests blocks deeper than the limit.
- `[tool.filepawl.nesting]` policy: `include`, `max_depth`, `exempt`, `enabled`. An exemption that excuses nothing fails.
- `filepawl init` stub includes the nesting block.

### Known limitations

- Barrels gate misses forwarders that pass an argument by keyword and forwarders whose call chain starts with a call.

## 0.1.0 - 2026-09-21

### Added

- Length gate with ratchet: cap, cap_tests, watch line, and allowance tracking.
- Directory-count gate: per-directory file cap with test directory handling.
- `check` command: scans tree, reports findings sorted by path, prints exact `filepawl accept` command when findings are fixable.
- `accept` command: adds missing allowance entries, lowers entries for shrunk files, drops stale entries, preserves per-entry reason annotations.
- `init` command: writes `.filepawl.toml` state file from the current tree, appends commented default policy to `pyproject.toml` if absent.
- `mv` command: moves a file or module, rewrites imports via pluggable backend, updates allowance entries, reports stale references found in tree.
- Exit codes: 0 for clean, 1 for findings, 2 for configuration or state error.
- Policy configuration in `pyproject.toml` `[tool.filepawl]`: languages, tests glob, per-gate caps and settings, per-language include patterns, mover selection, exemptions from hard cap.
- State file in `.filepawl.toml`: allowance table with file paths and line counts, per-entry reason field, version tracking.
- Rope mover backend: moves Python modules with rope's MoveModule and rewrites importers (optional extra dependency).
- Command mover backend: renders `mover_command` template with `{old}` and `{new}` shell-quoted paths, runs via shell.
- Gate and mover entry points: third-party gates register under `filepawl.gates`, movers under `filepawl.movers`; all discovered gates run on every `check`.
- Pre-commit hook configuration in `.pre-commit-hooks.yaml`: whole-tree scan with `pass_filenames: false` and `always_run: true`.

### Known limitations

- No include-set exclusion: excluded files (e.g., via build tool wiring) still receive allowance entries; exemption in policy removes only the hard cap check, not the ratchet or entry requirement.
- `mv` with the rope backend moves a module without renaming it: imports are rewritten to reflect the new location, but the module name itself does not change if the destination directory name differs from the package name.
