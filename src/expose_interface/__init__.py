"""Export ordinary Python callables as command line programs."""

from .errors import CommandError, DefinitionError, UsageError
from .definitions import Parameter, Program, argument, arguments, flag, option
from .interface import Interface, cli, command, expose, get_interface, interface, program

__all__ = [
    "CommandError", "DefinitionError", "UsageError", "Interface", "Parameter", "Program",
    "argument", "arguments", "flag", "option", "program", "expose", "command", "cli",
    "interface", "get_interface", "main",
]


def main() -> None:
    """Run the explicit module launcher."""
    from .__main__ import main as launch

    launch()
