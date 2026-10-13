"""Explicit ownership and module-scoped command registration."""

from collections.abc import Callable
import inspect

from .definitions import INFER, Program, make_program, validate_name
from .errors import DefinitionError


class Interface:
    """A reusable command tree with no import-time execution."""

    def __init__(self, name: str, *, description: str = "", setup: Callable | None = None):
        self.name = validate_name(name)
        if not isinstance(description, str):
            raise DefinitionError("description must be a string.")
        if setup is not None and not callable(setup):
            raise DefinitionError("setup must be callable.")
        self.description = description
        self.setup = setup
        self._programs: dict[str | None, Program] = {}
        self._children: dict[str, Interface] = {}

    @property
    def programs(self) -> tuple[Program, ...]:
        """Registered declarations in insertion order."""
        return tuple(self._programs.values())

    @property
    def children(self) -> dict[str, "Interface"]:
        """A copy of the mounted children, keyed by shell name."""
        return dict(self._children)

    def program(self, function=None, *, name=INFER, argument=None, arguments=None, order=None, section=None):
        def decorate(target):
            record = make_program(target, name=name, argument=argument, arguments=arguments, order=order, section=section)
            if record.name in self._programs or record.name in self._children:
                raise DefinitionError(f"Duplicate program {record.name!r} in {self.name!r}.")
            self._programs[record.name] = record
            return target

        return decorate if function is None else decorate(function)

    expose = command = cli = program

    def invoke(self, argv=None, *, prog_name=None):
        """Parse and execute, returning the selected callable's Python result."""
        from .runtime import invoke

        return invoke(self, argv, prog_name=prog_name)

    async def invoke_async(self, argv=None, *, prog_name=None):
        """Parse and execute inside the caller's event loop."""
        from .runtime import invoke_async

        return await invoke_async(self, argv, prog_name=prog_name)

    def main(self, argv=None, *, prog_name=None):
        """Console-script boundary: exit 0, 2 for usage, 1 for CommandError."""
        from .runtime import main

        main(self, argv, prog_name=prog_name)

    def add_interface(self, child: "Interface", *, name: str | None = None):
        if not isinstance(child, Interface):
            raise DefinitionError("Children must be Interface instances.")
        mount = validate_name(child.name if name is None else name)
        if mount in self._children or mount in self._programs:
            raise DefinitionError(f"Duplicate command {mount!r} in {self.name!r}.")
        if child is self or child._contains(self):
            raise DefinitionError("Interface trees cannot contain cycles.")
        self._children[mount] = child
        return child

    def _contains(self, interface):
        return any(child is interface or child._contains(interface) for child in self._children.values())


_interfaces: dict[tuple[str, str], Interface] = {}


def _caller_module():
    frame = inspect.currentframe()
    try:
        # This helper is called only from the public module-scoped functions.
        return frame.f_back.f_back.f_globals["__name__"]
    finally:
        del frame


def interface(name: str, *, description: str = "", setup=None, module: str | None = None) -> Interface:
    """Declare exactly one named interface in the calling module."""
    owner = module or _caller_module()
    key = (owner, name)
    if key in _interfaces:
        raise DefinitionError(f"Interface {name!r} already exists in module {owner!r}.")
    result = Interface(name, description=description, setup=setup)
    _interfaces[key] = result
    return result


def get_interface(name: str = ".", *, module: str | None = None) -> Interface:
    """Resolve an interface; create the default lazily for a module."""
    owner = module or _caller_module()
    key = (owner, name)
    if key not in _interfaces:
        if name != ".":
            raise DefinitionError(f"Unknown interface {name!r} in module {owner!r}.")
        default_name = owner.rsplit(".", 1)[-1].strip("_").replace("_", "-") or "program"
        _interfaces[key] = Interface(default_name)
    return _interfaces[key]


def program(function=None, *, interface=".", **kwargs):
    """Register a function in its defining module or an explicit interface."""
    def decorate(target):
        app = interface if isinstance(interface, Interface) else get_interface(interface, module=target.__module__)
        return app.program(target, **kwargs)

    return decorate if function is None else decorate(function)


expose = command = cli = program
