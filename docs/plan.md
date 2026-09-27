# filepawl build — orchestration plan

**Spec:** `docs/design.md` (authority; every task reads it). Repository rules: `CLAUDE.md`.

## Context

Repository is bare: `CLAUDE.md`, `docs/design.md`, nothing else. Spec is approved. This plan is the orchestration: phases, one commit per task, one fresh subagent per task, reviewer between tasks. The orchestrator writes no code; it dispatches, reads reviewer verdicts, relays fixes, and verifies `make check` output by quoting the decisive line.

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

**Model per agent, always explicit, never default.** haiku: soft-wrap, plan copy, test ports, README. sonnet: scaffold, policy loader, state file, tree scan, directory-count gate, gate registry, every reviewer. opus: length gate, check/accept/init commands, consumer acceptance, mover. Orchestrator itself writes nothing beyond one- or two-line edits.

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

### Soft-wrap the spec (1 agent, first commit `docs: soft-wrap design`)

Rewrap `docs/design.md` so every paragraph, list item and blockquote is one logical line. Tables, headings and fenced code unchanged. No word changed; verify with a diff of `tr -s '[:space:]' ' '` output before and after (identical). Commit that one path.

### Scaffold (1 agent, 1 commit `chore: scaffold package, venv, gates`)

Brief content: Create `pyproject.toml` (name filepawl, requires-python >=3.12, deps tomli-w, extras mv=[rope], dev group ruff/black/mypy/pytest/pre-commit, console script `filepawl = filepawl.cli:main`, tool config for ruff, black, mypy strict, pytest with `consumers` marker registered). Create `.venv` and install editable with dev extras. Create `Makefile` with `check` target running the five gates in order, `.pre-commit-config.yaml` consuming `.pre-commit-hooks.yaml` from `repo: local`-equivalent path `.`, `.pre-commit-hooks.yaml` with `id: filepawl`, `pass_filenames: false`, `always_run: true`. Create `filepawl/__init__.py`, `filepawl/errors.py`, `filepawl/cli.py` stub returning 0 for `--help` only, `tests/conftest.py` fixture above with a test for it, `.gitignore`. Copy this plan into `docs/plan.md` in its own commit, `docs: implementation plan`. `make check` is green with `filepawl check` a no-op subcommand printing nothing, marked in cli.py with a comment that the `feat: check, accept, init commands` task removes.

### Core modules (3 agents in parallel, 3 commits)

- **`feat: policy loader`** — `filepawl/config.py` + `tests/test_config.py`. Defaults per spec §4; unknown key, unknown mover name, non-int cap → ConfigError; `python` block default; free-form language block names; `gate_tables` keeps unknown `[tool.filepawl.<name>]` tables for third-party gates.
- **`feat: state file`** — `filepawl/state.py` + `tests/test_state.py`. Round trip; sorted; header comment regenerated; reason preserved; version check → StateError; absent file → empty.
- **`feat: tree scan and glob`** — `filepawl/tree.py` + `tests/test_tree.py`. `glob_match` cases: `**/*.py` matches `a.py`, `x/a.py`, `.claude/hooks/a.py`; `tests/**` matches `tests/a.py`, `tests/x/y.py`, not `testsx/a.py`; `**/*.sh`. Untracked file excluded (real git). Line count: trailing newline adds none, `\r\n` one, matches spec §6.1. `selected` narrowing.

### Gates (2 agents parallel, then 3 porting agents parallel)

- **`feat: length gate`** — `filepawl/gates/base.py`, `filepawl/gates/length.py`, `tests/test_length_gate.py`. Spec §6.1 exactly, including stale audit over whole table regardless of `selected`, exempt still needs entry, message texts: `grew past allowance; split it`, `shrank; run \`filepawl accept <path>\``, `back under watch line`, `drop it`. `accept` semantics from §7: add, lower, drop stale, never raise. Read the three consumer scripts before coding where spec is silent; disagreement between them not settled by §2 table → stop and report.
- **`feat: directory-count gate`** — `filepawl/gates/dircount.py`, `tests/test_dircount_gate.py`. §6.2; `accept` is identity.
- **`feat: gate registry`** — `filepawl/gates/registry.py`, `tests/test_gate_registry.py`. Built-ins; entry-point discovery via a distribution installed into a temp venv-less way: build a tiny wheel-less package under `tmp_path` with `entry_points.txt` in a `.dist-info` and prepend to `sys.path` with `importlib.metadata` honoring it. `enabled = false` disables.
- **`test: port <consumer> length cases`** — three rote agents, one per suite named in `CLAUDE.md`, each case cited by source test name in a docstring, appended to `tests/test_length_port_<consumer>.py`. Counts: hqptuner 33, triviajudge 16, gauntlet 19. A case whose behavior filepawl cannot reproduce is reported as a finding, not shimmed. If `tests/` directory would exceed dircount cap 30, use `tests/ports/`.

### CLI (1 agent, then 1 agent)

- **`feat: check, accept, init commands`** — `filepawl/cli.py`, `tests/test_cli.py`. §6.4 output: `path: message`, sorted, last line exact `filepawl accept ...` command when any finding fixable. Exit codes 0/1/2. `accept [PATH...] [--reason]` (reason with exactly one path else exit 2). `init`: refuses overwrite, appends `DEFAULT_POLICY_STUB` once. Split `cli.py` if over 400 lines (`cli_check.py`, `cli_accept.py`).
- **`test: consumer acceptance`** — `tests/test_consumers.py`, marker `consumers`, `skip` when checkout absent. For each of three: build policy in-test matching spec §10 step 2 (hqptuner: javascript block `**/*.js`,`**/*.css` + exempt junkcal fixture; gauntlet: `**/*.sh` in include; triviajudge: defaults), run accept-on-empty-state in memory against the checkout, compare to the script's `ALLOWANCE` dict parsed from the script source. Never write into a checkout. A mismatch is a filepawl defect: report, do not patch the test around it.

### Mover (1 agent, 1 commit `feat: mv command and movers`)

`filepawl/movers/{base,command,rope_mover,registry}.py`, `mv` in CLI, `tests/test_mv.py`. §8: language resolution, `command` backend with a fake script under `tmp_path`, plain `git mv` fallback, stale-ref grep finding `mock.patch("pkg.mod.fn")` and the relative path, allowance entry moved, exit 0 with leftovers printed and counted, `rope` missing → exit 2 with install line, rope test behind `importorskip`. Mover entry-point discovery test mirrors the gate registry's.

### Self-application and docs (1 agent, 1 commit `docs: README and self-check`)

`README.md`: install, policy, commands, agent teaching line, migration pointer. Confirm `make check`'s `filepawl check` runs default policy on own tree clean, `pre-commit run --all-files` green. Reconcile any §3 layout drift caused by splits, in the same commit.

### Barrels gate (spec §6.6)

- **`docs: barrels gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.6, §9, §10; `CLAUDE.md` ported-behavior list.
- **`feat: barrels policy`**: `BarrelsPolicy` in `filepawl/config.py` (`enabled`, `include`, `forwarders`, `module_exempt`, `forwarder_exempt`), `barrels` reserved, registry `_is_enabled` branch; tests in `tests/test_config.py`.
- **`feat: barrels gate`**: `filepawl/gates/barrels.py`, registered third among built-ins; tests in `tests/test_barrels_gate.py`.
- **`test: port barrels cases`**: the three suites named in `CLAUDE.md`, one file per consumer, each case citing its source.
- **`docs: barrels in README and changelog`**.

### Nesting gate (spec §6.7)

- **`docs: nesting gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.7, §9, §10; `CLAUDE.md` ported-behavior list.
- **`feat: nesting policy`**: `NestingPolicy` in `filepawl/config.py` (`enabled`, `include`, `max_depth`, `exempt`), `nesting` reserved, registry `_is_enabled` branch, policy stub; tests in `tests/test_config.py`.
- **`feat: nesting gate`**: `filepawl/gates/nesting.py`, registered fourth among built-ins; tests in `tests/test_nesting_gate.py`.
- **`test: port nesting cases`**: the three suites named in `CLAUDE.md`, one file per consumer, each case citing its source.
- **`docs: nesting in README and changelog`**.

### Edit-time notice and plugin (spec §7.1)

- **`docs: edit-time notice spec`**: `docs/design.md` §1, §2, §3, §7, §7.1, §9, §11; this phase.
- **`feat: hook command`**: `filepawl/hook.py`, `hook` subcommand in `filepawl/cli.py`; tests in `tests/test_hook.py`.
- **`feat: claude code plugin`**: `.claude-plugin/marketplace.json`, `plugin/.claude-plugin/plugin.json`, `plugin/hooks/hooks.json`, `plugin/hooks/filepawl-hook.sh`; tests in `tests/test_plugin.py`.
- **`docs: hook in README and changelog`**: `README.md`, `CHANGELOG.md`, version 0.3.0 in `pyproject.toml` and `plugin.json`.
- **`feat: deny edits that grow a file over its cap`**: `docs/design.md` §2, §7.1, §9; `filepawl/hook.py`; `tests/test_hook.py`; `plugin/hooks/filepawl-hook.sh` comment; `README.md`; `CHANGELOG.md`.

### Returns gate (spec §6.8)

- **`docs: returns gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.8, §9, §10; this phase.
- **`feat: returns policy`**: `ReturnsPolicy` in `filepawl/config.py` (`enabled`, `include`, `exempt`), `returns` reserved, registry `_is_enabled` branch, policy stub; tests in `tests/test_config.py` and `tests/test_gate_registry.py`.
- **`feat: returns gate`**: `filepawl/gates/returns.py`, registered fifth among built-ins; tests in `tests/test_returns_gate.py`.
- **`docs: returns in README and changelog`**: `README.md`, `CHANGELOG.md`, version 0.4.0 in `pyproject.toml` and `plugin.json`.

### Handlers gate (spec §6.10)

- **`docs: handlers gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.10, §9, §10; `docs/plan.md`.
- **`feat: handlers policy`**: `HandlersPolicy` in `filepawl/config.py` (`enabled`, `include`, `exempt`), `handlers` reserved, registry `_is_enabled` branch, `filepawl/policy_stub.py`; tests in `tests/test_config.py` and `tests/test_gate_registry.py`.
- **`feat: handlers gate`**: `filepawl/gates/handlers.py`, last entry of `_BUILTIN_GATES`; tests in `tests/test_handlers_gate.py`.
- **`docs: handlers in README and changelog`**: `README.md`, `CHANGELOG.md`, version 0.6.0 in `pyproject.toml` and `plugin.json`.

### Handlers follow-up (spec §6.10)

- **`fix: name every fix in the handlers finding`**: the finding text names propagating, raising a narrower exception and handling completely, in `filepawl/gates/handlers.py` and §6.10, tested in `tests/test_handlers_gate.py`.
- **`feat: handlers gate fails values assigned in handlers`**: a name assigned in a handler and read by a value return fails as a handler return does, in `filepawl/gates/handlers.py` and §2, §6.10 and §9, tested in `tests/test_handlers_gate.py`, with `README.md` and the `[Unreleased]` section of `CHANGELOG.md` to match.
- **`chore: release 0.7.0`**: the `[Unreleased]` section of `CHANGELOG.md` becomes 0.7.0, and `pyproject.toml` and `plugin.json` carry 0.7.0.

### Absence gate (spec §6.11)

- **`docs: absence gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.11, §9, §10; `docs/plan.md`.
- **`feat: absence policy`**: `AbsencePolicy` in `filepawl/config.py` (`enabled`, `include`, `exempt`), `absence` reserved, registry `_is_enabled` branch, `filepawl/policy_stub.py`; tests in `tests/test_config.py` and `tests/test_gate_registry.py`.
- **`test: give every absence-only test its contrast`**: each test in `tests/` that §6.11 fails is rewritten to assert its absence beside a case where the feature acts, keeping the behavior it names; no exemption is added.
- **`feat: absence gate`**: `filepawl/gates/absence.py`, last entry of `_BUILTIN_GATES`; tests in `tests/test_absence_gate.py`; `filepawl check` stays green on this tree.
- **`docs: absence in README and changelog`**: `README.md` and the `[Unreleased]` section of `CHANGELOG.md`.

### Test-suite gates (spec §6.12 to §6.19)

- **`docs: test-suite gates spec`**: `docs/design.md` §1, §2, §3, §4, §6.3, §6.12 to §6.19, §9, §10; `docs/plan.md`.
- **`chore: move the absence gate under gates/suite`**: `filepawl/gates/suite/`, `filepawl/config_suite.py` taking the absence policy out of `filepawl/config.py`, `tests/suite/`; no behavior changes.
- **`feat: own code`**: the `packages` key in `filepawl/config.py` and the derivation, own bindings and dotted names in `filepawl/gates/suite/common.py`; tests in `tests/suite/test_common.py`.
- **`docs: widen the mocks gate`**: `docs/design.md` §2, §4, §6.14, §9, the gate failing every patch whatever its target; `filepawl/policy_stub.py`; `docs/plan.md`.
- Per gate, in the order private, mocks, environment, snapshots, test names, existence, fakes: **`feat: <gate> policy`** in `filepawl/config_suite.py`, registry and stub; **`test: ...`** rewriting any test in this tree the gate fails, where one does, with no exemption; **`feat: <gate> gate`** in `filepawl/gates/suite/<gate>.py`, tests in `tests/suite/`, `filepawl check` green on this tree.
- **`docs: test-suite gates in README and changelog`**: `README.md` and the `[Unreleased]` section of `CHANGELOG.md`, the clocks gate included.

### Clocks gate (spec §6.20)

- **`docs: clocks gate spec`**: `docs/design.md` §1, §2, §3, §4, §6.12, §6.20, §9, §10; `docs/plan.md`; `CLAUDE.md` ported-behavior list.
- **`feat: clocks policy`**: `ClocksPolicy` in `filepawl/config_suite.py` (`enabled`, `include`, `exempt`, `names`), registry and stub; the site engine hands each gate the policy; tests in `tests/suite/test_config_suite.py` and `tests/test_gate_registry.py`.
- **`feat: clocks gate`**: `filepawl/gates/suite/clocks.py`, last entry of `_BUILTIN_GATES`; tests in `tests/suite/test_clocks_gate.py`, the ported cases citing their source; `filepawl check` green on this tree.

## Verification (orchestrator, end)

```
make check          # last line green; quote it
pre-commit run --all-files
.venv/bin/pytest -q -m consumers
git log --oneline   # one commit per task, prefixes correct
git status --short  # only the pre-existing staged deletion remains
```
