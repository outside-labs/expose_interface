"""A replacement adapter exercised against the Hidden Moves public API.

Requires an importable Hidden Moves source checkout or installation. The core
expose-interface distribution does not depend on Hidden Moves or Click.
"""

import argparse
import inspect
import json

from expose_interface import CommandError, Context, Interface, flag, option
from hidden_moves import MoveError, Moves, Registry, discover_providers, load_provider
from hidden_moves.adapters import CapabilityCatalog


def json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"Invalid value for --arguments: {error}") from error
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("Invalid value for --arguments: Expected a JSON object.")
    return parsed


@option("--plugin", dest="plugins", multiple=True, help="Explicitly load an installed provider.")
def setup(context: Context, plugins: tuple[str, ...] = ()):
    registry = Registry()
    if plugins:
        entries = discover_providers()
        for name in plugins:
            matches = [entry for entry in entries if entry.name == name]
            if len(matches) != 1:
                reason = "not installed" if not matches else "advertised by multiple packages"
                raise CommandError(f"Provider {name!r} is {reason}.")
            try:
                load_provider(matches[0], registry)
            except MoveError as error:
                raise CommandError(str(error)) from error
    context.obj = Moves(registry=registry)


app = Interface("hidden-moves", description="Discover and use reusable Python capabilities.", setup=setup)
moves = app.add_interface(Interface("moves", description="Inspect registered capabilities."))
plugins = app.add_interface(Interface("plugins", description="Inspect installed provider metadata."))


@moves.program(name="list")
@flag("--json", dest="as_json", help="Emit complete capability definitions as JSON.")
def list_moves(context: Context, as_json: bool = False):
    """List available capability definitions."""
    available = context.obj
    if as_json:
        print(json.dumps([available.explain(spec.qualified_name) for spec in available.moves()], indent=2))
        return
    for spec in available.moves():
        print(f"{spec.qualified_name}\t{spec.summary}")


@moves.program(name="show")
def show_move(context: Context, name: str):
    """Show a capability's structured definition."""
    try:
        print(json.dumps(context.obj.explain(name), indent=2))
    except MoveError as error:
        raise CommandError(str(error)) from error


@moves.program(name="call")
@option("--arguments", type=json_object, help="Arguments as a JSON object.")
async def call_move(context: Context, name: str, arguments: dict = {}):
    """Explicitly call one capability through its structured argument contract."""
    try:
        catalog = CapabilityCatalog(context.obj, [name])
        result = catalog.invoke(name, arguments)
        if inspect.isawaitable(result):
            result = await result
        print(json.dumps(catalog.serialize_result(name, result), indent=2, allow_nan=False))
    except MoveError as error:
        raise CommandError(str(error)) from error
    except Exception as error:
        raise CommandError(f"Capability {name!r} failed: {error}") from error


@plugins.program(name="list")
def list_plugins():
    """List provider metadata without loading provider code."""
    for entry in discover_providers():
        print(f"{entry.name}\t{entry.value}")


main = app.main

if __name__ == "__main__":
    main()
