# filepawl build — orchestration plan

**Spec:** `docs/design.md` (authority; every task reads it). Repository rules: `CLAUDE.md`.

## Context

Repository is bare: `CLAUDE.md`, `docs/design.md`, nothing else. Spec is approved. This plan is the orchestration: phases, one commit per task, one fresh subagent per task, reviewer between tasks. The orchestrator writes no code; it dispatches, reads reviewer verdicts, relays fixes, and verifies `make check` output by quoting the decisive line.

Git status already carries a staged deletion of `docs/superpowers/specs/2026-09-21-filepawl-design.md`. Not ours; every commit adds paths by name and leaves it staged-but-uncommitted. Report it at the end.

## Global constraints (from spec and rule sheet)

- Python floor 3.12. Runtime dep `tomli-w` only; `rope` under extra `mv`, imported lazily. No click, rich, pydantic. argparse.
- Tools in `.venv/bin`, configured in `pyproject.toml`. `make check` = `ruff check`, `black --check`, `mypy --strict filepawl`, `pytest -q`, `filepawl check` on own tree, default policy. Green before every commit.
- Test-first, real `git init` under `tmp_path`, no `git ls-files` stubs, no wall-clock waits. Consumer checkouts touched only by the `consumers`-marked acceptance test, read-only.
- `~/dev/hqptuner`, `~/dev/gauntlet`, `~/dev/triviajudge`: read, never write.
- Own tree: no `exempt`, no allowance entry. Module over 400 lines gets split.
- Commit prefixes `feat:/fix:/test:/docs:/chore:`; one task per commit; message names the task. Spec departures edit `docs/design.md` in the same commit and the message says which section.
- Markdown soft-wrapped, one paragraph per line.
- Nobody pushes.

## Execution protocol (orchestrator)

**Model per agent, always explicit, never default.** haiku: soft-wrap, plan copy, test ports 2d–2f, README. sonnet: scaffold, 1a–1c, 2b, 2c, every reviewer. opus: 2a, 3a, 3b, 4. Orchestrator itself writes nothing beyond one- or two-line edits.

1. Per task: dispatch one `general-purpose` agent with the brief below (imperatives only, 2–5 sentences, add the interface block verbatim). Agent runs TDD, runs `make check`, commits its own paths by name.
2. After the agent reports: dispatch `caveman:cavecrew-reviewer` on `git diff HEAD~1` plus spec conformance for the sections the task covers. Feed findings back to the same implementer via `SendMessage`; it fixes, re-runs `make check`, amends nothing — lands a `fix:` commit or, when unreviewed yet uncommitted, folds in.
3. Independent tasks in the same phase run in parallel (max 3 agents at once, half of nproc respected by default pytest).
4. Orchestrator verifies at phase end: one `make check` run, quote the last line.
5. A question the spec does not settle stops that task; the agent reports it, the orchestrator puts it to the owner as a blocking question. Not resolved by picking.

## Shared interfaces (pasted into every brief that touches them)

```
filepawl/errors.py
  class FilepawlError(Exception)        # CLI maps to exit 2
  class ConfigError(FilepawlError)
  class StateError(FilepawlError)

filepawl/config.py
  @dataclass(frozen=True) LanguagePolicy(include: tuple[str, ...], mover: str | None, mover_command: str | None)
  @dataclass(frozen=True) LengthPolicy(cap: int = 500, cap_tests: int = 800, watch: int = 400, enabled: bool = True)
  @dataclass(frozen=True) DircountPolicy(cap: int = 15, cap_tests: int = 30, exclude: tuple[str, ...] = ("__init__.py",), enabled: bool = True)
  @dataclass(frozen=True) Policy(languages: dict[str, LanguagePolicy], tests: tuple[str, ...], length: LengthPolicy, dircount: DircountPolicy, exempt: dict[str, str], gate_tables: dict[str, dict[str, object]])
  def default_policy() -> Policy
  def load_policy(root: Path) -> Policy          # reads pyproject.toml [tool.filepawl]; unknown key -> ConfigError
  DEFAULT_POLICY_STUB: str                       # commented block `init` appends

filepawl/state.py
  STATE_FILE = ".filepawl.toml"
  @dataclass(frozen=True) Entry(lines: int, reason: str | None = None)
  @dataclass(frozen=True) State(version: int = 1, allowance: dict[str, Entry] = ...)
  def load_state(root: Path) -> State            # absent file -> empty State; bad file -> StateError
  def write_state(root: Path, state: State) -> None   # wholesale rewrite, header comment, sorted by path

filepawl/tree.py
  def glob_match(pattern: str, path: str) -> bool     # ** matches zero or more segments incl. dot-dirs
  @dataclass(frozen=True) Tree(root: Path, files: tuple[str, ...], selected: tuple[str, ...] | None)
      # files: git ls-files output filtered through every language include; posix, relative
      # selected: argv paths narrowed to files, or None for whole tree
      def is_test(self, path: str) -> bool
      def language_of(self, path: str) -> str | None
      def line_count(self, path: str) -> int       # len(read_text(encoding="utf-8").splitlines())
  def find_root(start: Path) -> Path                  # git rev-parse --show-toplevel; missing git -> ConfigError
  def build_tree(root: Path, policy: Policy, paths: list[str] | None = None) -> Tree

filepawl/gates/base.py
  @dataclass(frozen=True, order=True) Finding(path: str, message: str, fixable_by_accept: bool = False)
  class Gate(Protocol):
      name: str
      def run(self, tree: Tree, policy: Policy, state: State) -> list[Finding]
      def accept(self, tree: Tree, policy: Policy, state: State) -> State

filepawl/gates/registry.py
  def discover_gates(policy: Policy) -> list[Gate]   # built-ins + entry points group "filepawl.gates"; drops those with enabled = false

filepawl/movers/base.py
  class Mover(Protocol):
      def move(self, old: Path, new: Path, root: Path) -> list[Path]
      def find_stale_refs(self, old_dotted: str, root: Path) -> list[str]

filepawl/movers/registry.py
  def discover_movers() -> dict[str, type[Mover]]    # "rope", "command", plus entry points group "filepawl.movers"

filepawl/cli.py
  def main(argv: list[str] | None = None) -> int     # 0 clean, 1 findings, 2 FilepawlError
```

Tests fixture, `tests/conftest.py`:

```
@pytest.fixture
def repo(tmp_path) -> Callable[[dict[str, str | int]], Path]
    # repo({"a.py": 10, "tests/t.py": "x\n"}) writes files (int = that many lines), git init, git add -A, returns root
```

## Phases and tasks

### Phase -1 — soft-wrap the spec (1 agent, first commit `docs: soft-wrap design`)

Rewrap `docs/design.md` so every paragraph, list item and blockquote is one logical line. Tables, headings and fenced code unchanged. No word changed; verify with a diff of `tr -s '[:space:]' ' '` output before and after (identical). Commit that one path.

### Phase 0 — scaffold (1 agent, 1 commit `chore: scaffold package, venv, gates`)

Brief content: Create `pyproject.toml` (name filepawl, requires-python >=3.12, deps tomli-w, extras mv=[rope], dev group ruff/black/mypy/pytest/pre-commit, console script `filepawl = filepawl.cli:main`, tool config for ruff, black, mypy strict, pytest with `consumers` marker registered). Create `.venv` and install editable with dev extras. Create `Makefile` with `check` target running the five gates in order, `.pre-commit-config.yaml` consuming `.pre-commit-hooks.yaml` from `repo: local`-equivalent path `.`, `.pre-commit-hooks.yaml` with `id: filepawl`, `pass_filenames: false`, `always_run: true`. Create `filepawl/__init__.py`, `filepawl/errors.py`, `filepawl/cli.py` stub returning 0 for `--help` only, `tests/conftest.py` fixture above with a test for it, `.gitignore`. Copy this plan into `docs/plan.md` (second commit `docs: implementation plan`). `make check` green with `filepawl check` temporarily a no-op subcommand printing nothing — mark it in cli.py with a comment removed by Phase 3.

### Phase 1 — core modules (3 agents in parallel, 3 commits)

- **1a `feat: policy loader`** — `filepawl/config.py` + `tests/test_config.py`. Defaults per spec §4; unknown key, unknown mover name, non-int cap → ConfigError; `python` block default; free-form language block names; `gate_tables` keeps unknown `[tool.filepawl.<name>]` tables for third-party gates.
- **1b `feat: state file`** — `filepawl/state.py` + `tests/test_state.py`. Round trip; sorted; header comment regenerated; reason preserved; version check → StateError; absent file → empty.
- **1c `feat: tree scan and glob`** — `filepawl/tree.py` + `tests/test_tree.py`. `glob_match` cases: `**/*.py` matches `a.py`, `x/a.py`, `.claude/hooks/a.py`; `tests/**` matches `tests/a.py`, `tests/x/y.py`, not `testsx/a.py`; `**/*.sh`. Untracked file excluded (real git). Line count: trailing newline adds none, `\r\n` one, matches spec §6.1. `selected` narrowing.

### Phase 2 — gates (2 agents parallel, then 3 porting agents parallel)

- **2a `feat: length gate`** — `filepawl/gates/base.py`, `filepawl/gates/length.py`, `tests/test_length_gate.py`. Spec §6.1 exactly, including stale audit over whole table regardless of `selected`, exempt still needs entry, message texts: `grew past allowance; split it`, `shrank; run \`filepawl accept <path>\``, `back under watch line`, `drop it`. `accept` semantics from §7: add, lower, drop stale, never raise. Read the three consumer scripts before coding where spec is silent; disagreement between them not settled by §2 table → stop and report.
- **2b `feat: directory-count gate`** — `filepawl/gates/dircount.py`, `tests/test_dircount_gate.py`. §6.2; `accept` is identity.
- **2c `feat: gate registry`** — `filepawl/gates/registry.py`, `tests/test_gate_registry.py`. Built-ins; entry-point discovery via a distribution installed into a temp venv-less way: build a tiny wheel-less package under `tmp_path` with `entry_points.txt` in a `.dist-info` and prepend to `sys.path` with `importlib.metadata` honoring it. `enabled = false` disables.
- **2d/2e/2f `test: port <consumer> length cases`** — three rote agents, one per suite named in `CLAUDE.md`, each case cited by source test name in a docstring, appended to `tests/test_length_port_<consumer>.py`. Counts: hqptuner 33, triviajudge 16, gauntlet 19. A case whose behavior filepawl cannot reproduce is reported as a finding, not shimmed. If `tests/` directory would exceed dircount cap 30, use `tests/ports/`.

### Phase 3 — CLI (1 agent, then 1 agent)

- **3a `feat: check, accept, init commands`** — `filepawl/cli.py`, `tests/test_cli.py`. §6.4 output: `path: message`, sorted, last line exact `filepawl accept ...` command when any finding fixable. Exit codes 0/1/2. `accept [PATH...] [--reason]` (reason with exactly one path else exit 2). `init`: refuses overwrite, appends `DEFAULT_POLICY_STUB` once. Remove the Phase 0 no-op. Split `cli.py` if over 400 lines (`cli_check.py`, `cli_accept.py`).
- **3b `test: consumer acceptance`** — `tests/test_consumers.py`, marker `consumers`, `skip` when checkout absent. For each of three: build policy in-test matching spec §10 step 2 (hqptuner: javascript block `**/*.js`,`**/*.css` + exempt junkcal fixture; gauntlet: `**/*.sh` in include; triviajudge: defaults), run accept-on-empty-state in memory against the checkout, compare to the script's `ALLOWANCE` dict parsed from the script source. Never write into a checkout. A mismatch is a filepawl defect: report, do not patch the test around it.

### Phase 4 — mover (1 agent, 1 commit `feat: mv command and movers`)

`filepawl/movers/{base,command,rope_mover,registry}.py`, `mv` in CLI, `tests/test_mv.py`. §8: language resolution, `command` backend with a fake script under `tmp_path`, plain `git mv` fallback, stale-ref grep finding `mock.patch("pkg.mod.fn")` and the relative path, allowance entry moved, exit 0 with leftovers printed and counted, `rope` missing → exit 2 with install line, rope test behind `importorskip`. Mover entry-point discovery test mirrors 2c.

### Phase 5 — self-application and docs (1 agent, 1 commit `docs: README and self-check`)

`README.md`: install, policy, commands, agent teaching line, migration pointer. Confirm `make check`'s `filepawl check` runs default policy on own tree clean, `pre-commit run --all-files` green. Reconcile `docs/design.md` status line (`implementation plan pending` → implemented) and any §3 layout drift caused by splits, in the same commit.

### Phase 6 — barrels gate (spec §6.6)

- **6a `docs: barrels gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.6, §9, §10; `CLAUDE.md` ported-behavior list; this phase.
- **6b `feat: barrels policy`**: `BarrelsPolicy` in `filepawl/config.py` (`enabled`, `include`, `forwarders`, `module_exempt`, `forwarder_exempt`), `barrels` reserved, registry `_is_enabled` branch; tests in `tests/test_config.py`.
- **6c `feat: barrels gate`**: `filepawl/gates/barrels.py`, registered third among built-ins; tests in `tests/test_barrels_gate.py`.
- **6d `test: port barrels cases`**: the three suites named in `CLAUDE.md`, one file per consumer, each case citing its source.
- **6f `docs: barrels in README and changelog`**.

### Phase 7 — nesting gate (spec §6.7)

- **7a `docs: nesting gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.7, §9, §10; `CLAUDE.md` ported-behavior list; this phase.
- **7b `feat: nesting policy`**: `NestingPolicy` in `filepawl/config.py` (`enabled`, `include`, `max_depth`, `exempt`), `nesting` reserved, registry `_is_enabled` branch, policy stub; tests in `tests/test_config.py`.
- **7c `feat: nesting gate`**: `filepawl/gates/nesting.py`, registered fourth among built-ins; tests in `tests/test_nesting_gate.py`.
- **7d `test: port nesting cases`**: the three suites named in `CLAUDE.md`, one file per consumer, each case citing its source.
- **7e `docs: nesting in README and changelog`**.

### Phase 8 — edit-time notice and plugin (spec §7.1)

- **`docs: edit-time notice spec`**: `docs/design.md` §1, §2, §3, §7, §7.1, §9, §11; this phase.
- **`feat: hook command`**: `filepawl/hook.py`, `hook` subcommand in `filepawl/cli.py`; tests in `tests/test_hook.py`.
- **`feat: claude code plugin`**: `.claude-plugin/marketplace.json`, `plugin/.claude-plugin/plugin.json`, `plugin/hooks/hooks.json`, `plugin/hooks/filepawl-hook.sh`; tests in `tests/test_plugin.py`.
- **`docs: hook in README and changelog`**: `README.md`, `CHANGELOG.md`, version 0.3.0 in `pyproject.toml` and `plugin.json`.
- **`feat: deny edits that grow a file over its cap`**: `docs/design.md` §2, §7.1, §9; `filepawl/hook.py`; `tests/test_hook.py`; `plugin/hooks/filepawl-hook.sh` comment; `README.md`; `CHANGELOG.md`.

## Verification (orchestrator, end)

```
make check          # last line green; quote it
pre-commit run --all-files
.venv/bin/pytest -q -m consumers
git log --oneline   # one commit per task, prefixes correct
git status --short  # only the pre-existing staged deletion remains
```
