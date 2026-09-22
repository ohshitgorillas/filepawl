"""Error types. The CLI maps any FilepawlError to exit code 2."""


class FilepawlError(Exception):
    """Base class for errors the CLI maps to exit 2."""


class ConfigError(FilepawlError):
    """Invalid or unparseable configuration."""


class StateError(FilepawlError):
    """Invalid or unparseable state file."""
