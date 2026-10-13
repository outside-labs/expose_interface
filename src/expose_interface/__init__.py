"""Export ordinary Python callables as command line programs."""

from .errors import CommandError, DefinitionError, UsageError

__all__ = ["CommandError", "DefinitionError", "UsageError", "main"]


def main() -> None:
    """Run the explicit module launcher."""
    from .__main__ import main as launch

    launch()
