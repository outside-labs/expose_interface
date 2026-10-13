"""The explicit development launcher."""

import argparse
from collections.abc import Sequence
import importlib
from importlib.metadata import version
import re

from .errors import DefinitionError
from .interface import Interface, get_interface


def _load(target: str) -> Interface:
    module_name, separator, attribute = target.partition(":")
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module_name):
        raise DefinitionError("Specify a Python module name, optionally followed by :INTERFACE.")
    if separator and not re.fullmatch(r"[A-Za-z_]\w*", attribute):
        raise DefinitionError("The interface selector must be a module attribute name.")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name or module_name.startswith(f"{error.name}."):
            raise DefinitionError(f"Module {module_name!r} is not importable.") from error
        raise
    if separator:
        app = getattr(module, attribute, None)
        if not isinstance(app, Interface):
            raise DefinitionError(f"{target!r} must select an Interface instance.")
        return app
    return get_interface(module=module_name)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="expose-interface",
        description="Export ordinary Python functions as command line programs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('expose-interface')}")
    parser.add_argument("module", nargs="?", metavar="MODULE[:INTERFACE]", help="Explicit module and optional Interface attribute to load.")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments passed to the selected interface.")
    parsed = parser.parse_args(argv)
    if parsed.module is None:
        parser.print_help()
        return
    try:
        app = _load(parsed.module)
    except DefinitionError as error:
        parser.error(str(error))
    app.main(parsed.arguments)


if __name__ == "__main__":
    main()
