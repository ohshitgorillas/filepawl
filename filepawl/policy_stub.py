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
