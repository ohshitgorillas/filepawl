"""Error types. The CLI maps any FilepawlError to exit code 2."""


class FilepawlError(Exception):
    """Base class for errors the CLI maps to exit 2."""


class ConfigError(FilepawlError):
    """Invalid or unparseable configuration."""


class StateError(FilepawlError):
    """Invalid or unparseable state file."""


class JudgeError(FilepawlError):
    """The judge cannot reach a verdict: no `claude`, or a call that failed twice."""
