"""The commented default policy block `filepawl init` writes (design.md §4, §7)."""

from __future__ import annotations

DEFAULT_POLICY_STUB = (
    "\n# filepawl policy; uncomment to override defaults\n"
    + "\n".join(
        "# " + line
        for line in [
            "[tool.filepawl]",
            'languages = ["python"]',
            'tests = ["tests/**"]',
            '# packages = ["mypkg"]  # own code; derived from the tree when absent',
            "",
            "[tool.filepawl.length]",
            "cap = 500",
            "cap_tests = 800",
            "watch = 400",
            "",
            "[tool.filepawl.dircount]",
            "cap = 15",
            "cap_tests = 30",
            'exclude = ["__init__.py"]',
            "",
            "[tool.filepawl.exempt]",
            "# path = reason. Human-edited. Exempts from the hard cap only; "
            "the file still",
            "# needs an allowance entry and may not grow.",
            '# "scripts/junkcal_fixture.py" = "junkcal fixture oracle, '
            'provenance kept whole"',
            "",
            "[tool.filepawl.barrels]",
            'include = ["**/*.py"]',
            'forwarders = ["**"]',
            "",
            "[tool.filepawl.barrels.module_exempt]",
            "# path = reason. Human-edited. A module that defines nothing on purpose.",
            "",
            "[tool.filepawl.barrels.forwarder_exempt]",
            '# "path::function" = reason. Human-edited. A forwarder that is the '
            "right shape.",
            "",
            "[tool.filepawl.nesting]",
            'include = ["**/*.py"]',
            "max_depth = 4",
            "",
            "[tool.filepawl.nesting.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "nests past the limit on purpose.",
            "",
            "[tool.filepawl.returns]",
            'include = ["**/*.py"]',
            "",
            "[tool.filepawl.returns.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function whose '
            "dict returns differ on purpose.",
            "",
            "[tool.filepawl.named_results]",
            'include = ["**/*.py"]',
            "exclude = []",
            "",
            "[tool.filepawl.handlers]",
            'include = ["**/*.py"]',
            "",
            "[tool.filepawl.handlers.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "returns from a handler on purpose.",
            "",
            "[tool.filepawl.absence]",
            'include = ["**/*.py"]',
            "",
            "[tool.filepawl.absence.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A test that '
            "asserts only an absent value on purpose.",
            "",
            "[tool.filepawl.private]",
            'include = ["**/*.py"]',
            "",
            "[tool.filepawl.private.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "reaches a private name on purpose.",
            "",
            "[tool.filepawl.mocks]",
            'include = ["**/*.py"]',
            "",
            "[tool.filepawl.mocks.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "patches on purpose.",
            "",
            "[tool.filepawl.clocks]",
            'include = ["**/*.py"]',
            'names = ["timeout", "interval", "delay"]',
            "",
            "[tool.filepawl.clocks.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function that '
            "runs on the wall clock on purpose.",
            "",
            "[tool.filepawl.judge]",
            "enabled = false",
            'model = "claude-sonnet-5"',
            "batch = 6",
            "timeout = 300",
            "",
            "[tool.filepawl.judge.exempt]",
            '# "path::qualified.name" = reason. Human-edited. A function the '
            "judge must not be asked about.",
            "",
            "[tool.filepawl.python]",
            'include = ["**/*.py"]',
            'mover = "rope"',
            "",
            "[tool.filepawl.javascript]",
            'include = ["**/*.js", "**/*.css"]',
            'mover = "command"',
            'mover_command = "npx jscodeshift -t scripts/move.js --old '
            '{old} --new {new} src/"',
        ]
    )
    + "\n"
)
