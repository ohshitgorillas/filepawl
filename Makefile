.PHONY: check

check:
	.venv/bin/ruff check .
	.venv/bin/black --check .
	.venv/bin/mypy --strict filepawl
	.venv/bin/pytest -q
	.venv/bin/filepawl check
