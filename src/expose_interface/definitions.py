"""Callable-preserving command and parameter declarations."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import inspect
import re
from typing import Any

from .errors import DefinitionError


class _Sentinel(Enum):
    INFER = "infer"
    MISSING = "missing"


INFER = _Sentinel.INFER
MISSING = _Sentinel.MISSING
_METADATA = "__expose_parameters__"


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise DefinitionError(f"Invalid command or interface name: {name!r}.")
    return name


@dataclass(frozen=True)
class Parameter:
    """An explicit CLI binding for one Python parameter."""

    dest: str
    kind: str
    names: tuple[str, ...] = ()
    type: Any = None
    default: Any = MISSING
    required: bool | None = None
    multiple: bool = False
    nargs: str | int | None = None
    choices: tuple[Any, ...] | None = None
    help: str = ""
    mtd: bool | str | Callable = False

    def __post_init__(self):
        if not isinstance(self.dest, str) or not self.dest.isidentifier():
            raise DefinitionError(f"Invalid parameter destination: {self.dest!r}.")
        if self.kind not in {"argument", "option", "flag"}:
            raise DefinitionError(f"Invalid parameter kind: {self.kind!r}.")
        if self.required is not None and type(self.required) is not bool:
            raise DefinitionError("required must be a Boolean.")
        if type(self.multiple) is not bool or not isinstance(self.help, str):
            raise DefinitionError("multiple must be a Boolean and help must be a string.")
        if self.kind == "argument" and self.names:
            raise DefinitionError("A positional argument cannot have option switches.")
        if self.kind != "argument":
            if not self.names or len(set(self.names)) != len(self.names):
                raise DefinitionError("Options need distinct switches.")
            for name in self.names:
                if not isinstance(name, str) or not re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9_-]*|-[A-Za-z0-9]", name):
                    raise DefinitionError(f"Invalid option switch: {name!r}.")
                if name in {"-h", "--help"}:
                    raise DefinitionError(f"{name} is reserved for help.")
        if self.kind == "flag" and (self.multiple or self.nargs is not None or self.choices is not None):
            raise DefinitionError("Boolean flags cannot have multiple values, nargs or choices.")
        if self.kind != "flag" and self.mtd is not False:
            raise DefinitionError("Only flags can declare a method callback.")
        if not isinstance(self.mtd, (bool, str)) and not callable(self.mtd):
            raise DefinitionError("mtd must be a Boolean, method name or callable.")


def parameters(function: Callable) -> tuple[Parameter, ...]:
    return getattr(function, _METADATA, ())


def _decorate(spec: Parameter):
    def decorate(function):
        existing = parameters(function)
        if any(item.dest == spec.dest for item in existing):
            raise DefinitionError(f"Parameter {spec.dest!r} is declared more than once.")
        switches = {name for item in existing for name in item.names}
        if switches.intersection(spec.names):
            raise DefinitionError("An option switch is declared more than once.")
        # Bound methods store metadata on their underlying function.
        target = function.__func__ if inspect.ismethod(function) else function
        setattr(target, _METADATA, (*existing, spec))
        return function

    return decorate


def argument(name: str, **kwargs):
    """Declare one positional parameter, without wrapping its callable."""
    return _decorate(_parameter(name, "argument", (), kwargs))


def arguments(*names: str):
    """Declare several positional parameters."""
    def decorate(function):
        for name in names:
            function = argument(name)(function)
        return function

    return decorate


def _parameter(dest, kind, names, kwargs):
    if "choices" in kwargs and kwargs["choices"] is not None:
        kwargs["choices"] = tuple(kwargs["choices"])
    try:
        return Parameter(dest, kind, names, **kwargs)
    except TypeError as error:
        raise DefinitionError(str(error)) from error


def _option(kind, names, dest, kwargs):
    if dest is None:
        name = next((name for name in names if name.startswith("--")), names[0] if names else "")
        dest = name.lstrip("-").replace("-", "_")
    return _decorate(_parameter(dest, kind, tuple(names), kwargs))


def option(*names: str, dest: str | None = None, **kwargs):
    """Declare a named option that consumes a value."""
    return _option("option", names, dest, kwargs)


def flag(*names: str, dest: str | None = None, mtd=False, **kwargs):
    """Declare a Boolean switch with an optional post-parse callback."""
    return _option("flag", names, dest, {"mtd": mtd, **kwargs})


@dataclass(frozen=True)
class Program:
    """One registered callable. Metadata is read when compiling the interface."""

    function: Callable
    name: str | None
    positional: tuple[str, ...] = ()
    order: int | None = None
    section: str | None = None

    @property
    def description(self) -> str:
        return inspect.getdoc(self.function) or ""

    @property
    def parameters(self) -> tuple[Parameter, ...]:
        explicit = parameters(self.function)
        overlap = set(self.positional).intersection(item.dest for item in explicit)
        if overlap:
            raise DefinitionError(f"Duplicate inline/decorator arguments: {sorted(overlap)}.")
        return (*explicit, *(Parameter(name, "argument") for name in self.positional))


def make_program(function, *, name=INFER, argument=None, arguments=None, order=None, section=None):
    if not callable(function):
        raise DefinitionError("Programs must be callable.")
    if name is INFER:
        name = function.__name__.replace("_", "-")
    if name is not None:
        validate_name(name)
    if argument is not None and arguments is not None:
        raise DefinitionError("Use argument or arguments, not both.")
    if argument is not None:
        arguments = (argument,)
    if isinstance(arguments, str) or (arguments is not None and not isinstance(arguments, Sequence)):
        raise DefinitionError("arguments must be a sequence of parameter names.")
    positional = tuple(arguments or ())
    for dest in positional:
        Parameter(dest, "argument")
    if len(set(positional)) != len(positional):
        raise DefinitionError("Inline arguments cannot contain duplicate names.")
    if order is not None and (isinstance(order, bool) or not isinstance(order, int)):
        raise DefinitionError("order must be an integer.")
    if section is not None and not isinstance(section, str):
        raise DefinitionError("section must be a string.")
    result = Program(function, name, positional, order, section)
    result.parameters
    return result
