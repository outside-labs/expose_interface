"""Compile trusted Python declarations into strict argparse trees."""

import argparse
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import inspect
from pathlib import Path
import sys
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from .definitions import MISSING, Parameter, Program
from .errors import DefinitionError, UsageError
from .runtime import Context


class _HelpRequested(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        if sys.version_info >= (3, 14):
            kwargs.setdefault("color", False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise UsageError(f"{self.format_usage().rstrip()}\n{self.prog}: error: {message}")

    def exit(self, status=0, message=None):
        if status:
            raise UsageError(message or f"{self.prog}: invalid input")
        raise _HelpRequested


class _FlagAction(argparse.BooleanOptionalAction):
    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string)
        # Subparser namespaces merge by key. Each binding needs its own marker
        # so a child's selections cannot replace those from its parent.
        setattr(namespace, f"{self.dest}_selected", getattr(namespace, self.dest))


class _AppendAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        supplied = getattr(namespace, "_expose_supplied_options", set())
        items = getattr(namespace, self.dest) if self.dest in supplied else []
        items.append(values)
        setattr(namespace, self.dest, items)
        supplied.add(self.dest)
        namespace._expose_supplied_options = supplied


@dataclass(frozen=True, eq=False)
class _DefaultValue:
    """Keep already typed string defaults out of argparse's conversion path."""

    value: str

    def __eq__(self, other):
        return self.value == (other.value if isinstance(other, _DefaultValue) else other)

    def __hash__(self):
        return hash(self.value)


@dataclass(frozen=True)
class Binding:
    parameter: inspect.Parameter
    spec: Parameter | None
    key: str
    collection: type | None = None
    callback: Callable | None = None
    injected: bool = False

    def value(self, namespace):
        value = getattr(namespace, self.key)
        if isinstance(value, _DefaultValue):
            value = value.value
        return self.collection(value) if self.collection and value is not None else value


@dataclass(frozen=True)
class Compiled:
    record: Program
    bindings: tuple[Binding, ...]


@dataclass(frozen=True)
class Plan:
    setups: tuple[Compiled, ...]
    program: Compiled
    path: tuple[str, ...]


def _shape(annotation):
    origin = get_origin(annotation)
    nullable = False
    if origin in (Union, UnionType):
        types = get_args(annotation)
        remaining = tuple(item for item in types if item is not type(None))
        if len(remaining) != 1 or len(types) != 2:
            raise DefinitionError(f"Unsupported union: {annotation!r}.")
        annotation, nullable = remaining[0], True
        origin = get_origin(annotation)
    collection = None
    if origin in (list, tuple):
        args = get_args(annotation)
        if origin is tuple and (len(args) != 2 or args[1] is not Ellipsis):
            raise DefinitionError("Tuple inputs must use tuple[T, ...].")
        if origin is list and len(args) != 1:
            raise DefinitionError("List inputs must use list[T].")
        annotation, collection = args[0], origin
    return annotation, collection, nullable


def _converter(annotation, *, explicit=False):
    if annotation in (str, int, float, Path):
        return annotation
    if get_origin(annotation) is Literal:
        choices = get_args(annotation)
        if not choices or any(type(value) not in (str, int, float) for value in choices):
            raise DefinitionError("Literal inputs must contain strings, integers or floats.")
        def convert(value):
            matches = [choice for choice in choices if str(choice) == value]
            if len(matches) != 1:
                raise ValueError(f"expected one of {', '.join(map(str, choices))}")
            return matches[0]
        return convert
    if inspect.isclass(annotation) and issubclass(annotation, Enum):
        def convert(value):
            matches = [choice for choice in annotation if str(choice.value) == value]
            if len(matches) != 1:
                raise ValueError(f"expected one of {', '.join(str(item.value) for item in annotation)}")
            return matches[0]
        return convert
    if explicit and callable(annotation) and annotation is not bool:
        return annotation
    raise DefinitionError(f"Unsupported input type: {annotation!r}. Use an explicit converter.")


def _callback(function, spec):
    if spec.mtd is False:
        return None
    target = spec.mtd
    if isinstance(target, (bool, str)):
        owner = getattr(function, "__self__", None)
        if owner is None:
            raise DefinitionError("Method flag callbacks require a bound program method.")
        name = spec.dest if target is True else target
        target = getattr(owner, name, None)
    if not callable(target):
        raise DefinitionError(f"Callback for flag {spec.dest!r} is not callable.")
    try:
        inspect.signature(target).bind()
    except (TypeError, ValueError) as error:
        raise DefinitionError(f"Flag callback {spec.dest!r} must accept no required arguments.") from error
    return target


def _validate_default(value, annotation, collection, nullable, kind):
    if value is None:
        if not nullable:
            raise DefinitionError(f"None is not a valid default for {annotation!r}.")
        return
    if collection:
        if not isinstance(value, (list, tuple)):
            raise DefinitionError("Collection inputs need list/tuple defaults.")
        for item in value:
            _validate_default(item, annotation, None, False, kind)
        return
    if annotation in (str, int, float, bool, Path):
        valid = isinstance(value, annotation)
        if annotation in (int, float) and isinstance(value, bool):
            valid = False
        if annotation is float and type(value) is int:
            valid = True
        if not valid:
            raise DefinitionError(f"Invalid default {value!r} for {annotation.__name__}.")
    elif get_origin(annotation) is Literal and value not in get_args(annotation):
        raise DefinitionError(f"Default {value!r} is outside {annotation!r}.")
    elif inspect.isclass(annotation) and issubclass(annotation, Enum) and not isinstance(value, annotation):
        raise DefinitionError(f"Default must be an instance of {annotation.__name__}.")


def _compile(record, parser, counter):
    try:
        signature = inspect.signature(record.function)
        hints = get_type_hints(record.function)
    except (TypeError, ValueError, NameError) as error:
        raise DefinitionError(f"Cannot resolve signature for {record.function}: {error}") from error
    declarations = {item.dest: item for item in record.parameters}
    unknown = set(declarations).difference(signature.parameters)
    if unknown:
        raise DefinitionError(f"Declared parameters are absent from the signature: {sorted(unknown)}.")
    bindings = []
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise DefinitionError("Variadic Python signatures are unsupported; use a typed collection parameter.")
        annotation = hints.get(parameter.name, parameter.annotation)
        counter[0] += 1
        key = f"_expose_{counter[0]}_{parameter.name}"
        if annotation is Context:
            if parameter.name in declarations:
                raise DefinitionError("Context is injected and cannot have a CLI declaration.")
            bindings.append(Binding(parameter, None, key, injected=True))
            continue
        explicit = declarations.get(parameter.name)
        default = parameter.default if parameter.default is not inspect.Parameter.empty else MISSING
        if explicit and explicit.default is not MISSING:
            default = explicit.default
        if annotation is inspect.Parameter.empty:
            if default is MISSING:
                annotation = str
            elif default is None:
                annotation = str | None
            elif isinstance(default, (list, tuple)):
                annotation = list[str] if isinstance(default, list) else tuple[str, ...]
            else:
                annotation = type(default)
        if explicit and explicit.type is not None:
            annotation = explicit.type
        scalar, collection, nullable = _shape(annotation)
        kind = explicit.kind if explicit else (
            "argument" if default is MISSING and parameter.kind is not inspect.Parameter.KEYWORD_ONLY else
            "flag" if scalar is bool and collection is None else "option"
        )
        spec = explicit or Parameter(
            parameter.name, kind,
            () if kind == "argument" else ("--" + parameter.name.replace("_", "-"),),
        )
        if collection and scalar is bool:
            raise DefinitionError("Collections of Boolean flags are unsupported.")
        if spec.multiple:
            if kind == "argument" or spec.nargs is not None:
                raise DefinitionError("multiple applies only to value options without nargs.")
            collection = collection or (tuple if isinstance(default, tuple) else list)
        if spec.nargs not in (None, "?", "*", "+") and (type(spec.nargs) is not int or spec.nargs < 1):
            raise DefinitionError(f"Invalid nargs: {spec.nargs!r}.")
        if spec.nargs in ("*", "+") or isinstance(spec.nargs, int):
            if not collection:
                raise DefinitionError("Multi-value nargs requires a collection annotation or multiple option.")
        if collection and spec.nargs == "?":
            raise DefinitionError("Collection inputs cannot use nargs='?'.")
        required = default is MISSING if spec.required is None else spec.required
        if kind == "argument" and required and spec.nargs in ("?", "*"):
            raise DefinitionError("Required positional inputs cannot have optional nargs.")
        if kind == "option" and spec.nargs == "?" and not nullable:
            raise DefinitionError("Options with nargs='?' require a nullable annotation.")
        if kind == "flag":
            if scalar is not bool or collection:
                raise DefinitionError(f"Flag {parameter.name!r} requires a Boolean parameter.")
            default = False if default is MISSING else default
            if type(default) is not bool:
                raise DefinitionError("Boolean flags require Boolean defaults.")
            converter = None
        else:
            converter = _converter(scalar, explicit=explicit is not None and explicit.type is not None)
        if default is not MISSING:
            _validate_default(default, scalar, collection, nullable, kind)
        elif not required:
            default = [] if collection else None
        # Argparse converts string defaults. Copy defaults to prevent state leakage.
        parser_default = list(default) if collection and default is not MISSING and default is not None else default
        if isinstance(parser_default, str):
            parser_default = _DefaultValue(parser_default)
        values = {"dest": key, "default": deepcopy(parser_default) if default is not MISSING else None, "help": spec.help.replace("%", "%%")}
        if kind == "flag":
            values.update(action=_FlagAction, required=bool(spec.required))
        else:
            values["type"] = converter
            if spec.choices is not None:
                values["choices"] = spec.choices
                if default is not MISSING and default is not None:
                    defaults = default if collection else [default]
                    if any(value not in spec.choices for value in defaults):
                        raise DefinitionError("Default is outside the declared choices.")
            if kind == "argument":
                values.pop("dest")
                values["metavar"] = parameter.name
                nargs = spec.nargs
                if nargs is None:
                    nargs = ("+" if required else "*") if collection else (None if required else "?")
                if nargs is not None:
                    values["nargs"] = nargs
                names = (key,)
            else:
                values.update(required=required, metavar=parameter.name.upper())
                if spec.nargs is not None:
                    values["nargs"] = spec.nargs
                elif collection:
                    values["action"] = _AppendAction
        if kind != "argument":
            names = spec.names
        try:
            parser.add_argument(*names, **values)
        except (argparse.ArgumentError, TypeError, ValueError) as error:
            raise DefinitionError(str(error)) from error
        bindings.append(Binding(parameter, spec, key, collection, _callback(record.function, spec)))
    return Compiled(record, tuple(bindings))


def build(app, *, prog_name=None):
    counter = [0]
    root = _Parser(prog=prog_name or app.name, description=app.description)

    def node(interface, parser, setups=(), path=()):
        parser.set_defaults(_expose_plan=None, _expose_parser=parser)
        if interface.setup:
            setups = (*setups, _compile(Program(interface.setup, None), parser, counter))
        default = interface._programs.get(None)
        if default:
            if default.description:
                parser.description = "\n\n".join(filter(None, (interface.description, default.description)))
            compiled = _compile(default, parser, counter)
            if (interface.children or any(p.name is not None for p in interface.programs)) and any(b.spec and b.spec.kind == "argument" for b in compiled.bindings):
                raise DefinitionError("A default program with positional arguments cannot share an interface with subcommands.")
            parser.set_defaults(_expose_plan=Plan(setups, compiled, path))
        entries = []
        for record in interface.programs:
            if record.name is not None:
                entries.append((record.section or "", record.order, record.name, record.description))
        for name, child in interface._children.items():
            order, section = interface._presentation[name]
            entries.append((section or "", order, name, child.description))
        entries.sort(key=lambda item: (item[0], item[1] if item[1] is not None else float("inf"), item[2]))
        commands = [entry[2] for entry in entries]
        if commands:
            lines = []
            section = None
            width = max(len(name) for name in commands)
            for group, _, name, description in entries:
                if group != section:
                    lines.extend(([""] if lines else []) + [f"{group or 'Programs'}:"])
                    section = group
                summary = description.splitlines()[0] if description else ""
                lines.append(f"  {name:<{width}}  {summary}".rstrip())
            parser.epilog = "\n".join(lines)
            subparsers = parser.add_subparsers(metavar="COMMAND")
            for name in commands:
                if name in interface._children:
                    child = interface._children[name]
                    child_parser = subparsers.add_parser(name, description=child.description)
                    node(child, child_parser, setups, (*path, name))
                else:
                    record = interface._programs[name]
                    child_parser = subparsers.add_parser(name, description=record.description)
                    compiled = _compile(record, child_parser, counter)
                    child_parser.set_defaults(_expose_plan=Plan(setups, compiled, (*path, name)), _expose_parser=child_parser)

    node(app, root)
    return root


def prepare(app, argv=None, *, prog_name=None):
    parser = build(app, prog_name=prog_name)
    try:
        namespace = parser.parse_args(argv)
    except _HelpRequested:
        return None
    plan = namespace._expose_plan
    if plan is None:
        namespace._expose_parser.print_help()
        return None
    return plan, namespace
