"""Errors at declaration, parsing and command execution boundaries."""


class DefinitionError(ValueError):
    """An application declared an invalid or ambiguous interface."""


class UsageError(ValueError):
    """Command line input does not match the declared interface."""


class CommandError(Exception):
    """An expected application failure to display without a traceback."""
