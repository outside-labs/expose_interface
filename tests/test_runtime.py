"""Typed conversion, routing and execution boundaries."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Literal
import unittest

from expose_interface import CommandError, Context, DefinitionError, Interface, UsageError, argument, flag, option


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class RuntimeTests(unittest.TestCase):
    def test_inferred_scalars_and_positional_only(self):
        app = Interface("app")

        @app.program
        def add(value: int, /, count: int = 1, *, ratio: float = 0.5, path: Path = Path(".")):
            return value + count, ratio, path

        self.assertEqual(app.invoke(["add", "4", "--count", "3", "--ratio", "2", "--path", "file"]), (7, 2.0, Path("file")))
        with self.assertRaises(UsageError):
            app.invoke(["add", "bad"])
        with self.assertRaises(UsageError):
            app.invoke(["add", "4", "--cou", "3"])

    def test_enum_literal_nullable_and_custom_converter(self):
        app = Interface("app")

        @app.program
        @option("--label", type=str.upper)
        def run(color: Color = Color.RED, mode: Literal["fast", "slow"] = "fast", limit: int | None = None, label: str = "DEFAULT"):
            return color, mode, limit, label

        self.assertEqual(app.invoke(["run", "--color", "blue", "--mode", "slow", "--limit", "4", "--label", "hi"]), (Color.BLUE, "slow", 4, "HI"))
        self.assertEqual(app.invoke(["run"]), (Color.RED, "fast", None, "DEFAULT"))
        for argv in (["--color", "green"], ["--mode", "other"], ["--limit", "bad"]):
            with self.subTest(argv=argv), self.assertRaises(UsageError):
                app.invoke(["run", *argv])

    def test_required_keyword_only_and_explicit_positional(self):
        app = Interface("app")

        @app.program(argument="value")
        def run(value: str = "default", *, count: int):
            return value, count

        self.assertEqual(app.invoke(["run", "chosen", "--count", "2"]), ("chosen", 2))
        self.assertEqual(app.invoke(["run", "--count", "2"]), ("default", 2))
        with self.assertRaises(UsageError):
            app.invoke(["run"])

    def test_collection_arguments_and_repeated_options(self):
        app = Interface("app")

        @app.program
        @option("--plugin", dest="plugins", multiple=True)
        def run(values: list[int], plugins: tuple[str, ...] = ("default",)):
            return values, plugins

        self.assertEqual(app.invoke(["run", "1", "2", "--plugin", "a", "--plugin", "b"]), ([1, 2], ("a", "b")))
        self.assertEqual(app.invoke(["run", "3"]), ([3], ("default",)))
        with self.assertRaises(UsageError):
            app.invoke(["run"])

    def test_mutating_collection_defaults_does_not_leak(self):
        app = Interface("app")

        @app.program
        def run(values: list[str] = []):
            values.append("changed")
            return values

        self.assertEqual(app.invoke(["run"]), ["changed"])
        self.assertEqual(app.invoke(["run"]), ["changed"])
        self.assertEqual(app.invoke(["run", "--values", "one", "--values", "two"]), ["one", "two", "changed"])

    def test_collection_nargs_and_choices(self):
        app = Interface("app")

        @app.program
        @option("--values", nargs="+", choices=[1, 2, 3])
        def run(values: tuple[int, ...] = ()):
            return values

        self.assertEqual(app.invoke(["run", "--values", "1", "2"]), (1, 2))
        with self.assertRaises(UsageError):
            app.invoke(["run", "--values", "4"])

    def test_flags_callbacks_and_negative_forms(self):
        effects = []
        app = Interface("app")

        @app.program
        @flag("--color", "-G", mtd=lambda: effects.append("color"))
        def run(color: bool = False, enabled: bool = True):
            effects.append("program")
            return color, enabled

        self.assertEqual(app.invoke(["run", "-G", "--no-enabled"]), (True, False))
        self.assertEqual(effects, ["color", "program"])
        effects.clear()
        self.assertEqual(app.invoke(["run", "--color", "--no-color"]), (False, True))
        self.assertEqual(effects, ["program"])

    def test_bound_method_flag_callback(self):
        class Tool:
            def __init__(self):
                self.events = []

            def color(self):
                self.events.append("color")

            @flag("--color", mtd=True)
            def run(self, color: bool = False):
                return color

        tool = Tool()
        app = Interface("app")
        app.program(tool.run)
        self.assertTrue(app.invoke(["run", "--color"]))
        self.assertEqual(tool.events, ["color"])

    def test_named_method_callback(self):
        class Tool:
            def select(self):
                self.selected = True

            @flag("--active", mtd="select")
            def run(self, active: bool = False):
                return active

        tool = Tool()
        app = Interface("app")
        app.program(tool.run)
        self.assertTrue(app.invoke(["run", "--active"]))
        self.assertTrue(tool.selected)

    def test_help_and_bad_input_never_execute_callbacks_or_setup(self):
        effects = []
        app = Interface("app", setup=lambda: effects.append("setup"))

        @app.program
        @flag("--color", mtd=lambda: effects.append("color"))
        def run(value: int, color: bool = False):
            effects.append("program")

        for argv in (["--help"], ["run", "--help"], ["run", "-h"]):
            with self.subTest(argv=argv), redirect_stdout(StringIO()):
                app.invoke(argv)
        for argv in (["run", "--color", "bad"], ["run", "--color", "1", "--unknown"], ["unknown"]):
            with self.subTest(argv=argv), self.assertRaises(UsageError):
                app.invoke(argv)
        self.assertEqual(effects, [])

    def test_nested_setup_context_and_global_options(self):
        calls = []

        @option("--plugin", dest="plugins", multiple=True)
        def setup(context: Context, plugins: tuple[str, ...] = ()):
            context.obj = list(plugins)
            calls.append("root")

        def child_setup(context: Context):
            context.obj.append("child")
            calls.append("child")

        root = Interface("app", setup=setup)
        child = Interface("tools", setup=child_setup)
        root.add_interface(child)

        @child.program
        def run(context: Context, value: str):
            return context.obj, value, context.path

        self.assertEqual(root.invoke(["--plugin", "one", "--plugin", "two", "tools", "run", "ok"]), (["one", "two", "child"], "ok", ("tools", "run")))
        self.assertEqual(root.invoke(["tools", "run", "next"])[0], ["child"])
        self.assertEqual(calls, ["root", "child", "root", "child"])

    def test_same_parameter_names_at_different_depths(self):
        def setup(context: Context, value: int = 1):
            context.obj = value

        root = Interface("app", setup=setup)
        child = Interface("child")
        root.add_interface(child)

        @child.program
        def run(context: Context, value: int = 2):
            return context.obj, value

        self.assertEqual(root.invoke(["--value", "3", "child", "run", "--value", "4"]), (3, 4))

    def test_default_program_and_ambiguous_routes(self):
        app = Interface("app")
        app.program(lambda value: value.upper(), name=None)
        self.assertEqual(app.invoke(["hello"]), "HELLO")
        app.program(lambda: None, name="other")
        with self.assertRaises(DefinitionError):
            app.invoke(["--help"])
        other = Interface("other")
        other.program(lambda: 7, name=None)
        other.program(lambda: 8, name="run")
        self.assertEqual(other.invoke([]), 7)
        self.assertEqual(other.invoke(["run"]), 8)

    def test_main_exit_codes_and_unexpected_errors(self):
        app = Interface("app")

        @app.program
        def run(value: int):
            return value

        @app.program
        def fail():
            raise CommandError("expected failure")

        @app.program
        def bug():
            raise RuntimeError("programming failure")

        for argv, status in ((["run", "7"], 0), (["run", "bad"], 2), (["fail"], 1), (["--help"], 0)):
            with self.subTest(argv=argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
                app.main(argv)
            self.assertEqual(caught.exception.code, status)
        with self.assertRaisesRegex(RuntimeError, "programming failure"):
            app.main(["bug"])

    def test_async_setup_callback_command_and_custom_awaitable(self):
        effects = []

        async def setup(context: Context):
            context.obj = 3
            effects.append("setup")

        async def callback():
            effects.append("callback")

        app = Interface("app", setup=setup)

        @app.program
        @flag("--active", mtd=callback)
        async def run(context: Context, active: bool = False):
            effects.append("run")
            return context.obj + int(active)

        self.assertEqual(app.invoke(["run", "--active"]), 4)
        self.assertEqual(effects, ["setup", "callback", "run"])
        self.assertEqual(asyncio.run(app.invoke_async(["run"])), 3)

        class Awaitable:
            def __await__(self):
                async def result():
                    return 9
                return result().__await__()

        app.program(lambda: Awaitable(), name="custom")
        self.assertEqual(app.invoke(["custom"]), 9)

    def test_sync_invocation_inside_event_loop_has_actionable_error(self):
        app = Interface("app")
        app.program(lambda: None, name="run")

        async def run():
            with self.assertRaisesRegex(RuntimeError, "invoke_async"):
                app.invoke(["run"])

        asyncio.run(run())

    def test_invalid_declarations_fail_before_execution(self):
        def variadic(*values):
            raise AssertionError

        def mapping(values: dict):
            raise AssertionError

        def union(value: int | str):
            raise AssertionError

        def invalid_default(value: int = "bad"):
            raise AssertionError

        def typed_tuple(values: tuple[int, str]):
            raise AssertionError

        for function in (variadic, mapping, union, invalid_default, typed_tuple):
            with self.subTest(function=function.__name__), self.assertRaises(DefinitionError):
                app = Interface("app")
                app.program(function)
                app.invoke(["--help"])

    def test_missing_parameter_and_bad_callbacks_fail_at_compilation(self):
        cases = [
            option("--missing")(lambda: None),
            flag("--value")(lambda value=3: None),
            flag("--value", mtd=True)(lambda value=False: None),
            flag("--value", mtd=lambda required: None)(lambda value=False: None),
        ]
        for function in cases:
            with self.subTest(function=function), self.assertRaises(DefinitionError):
                app = Interface("app")
                app.program(function, name="run")
                app.invoke(["--help"])

    def test_generated_negative_switch_conflicts_are_definition_errors(self):
        app = Interface("app")

        @app.program
        @option("--no-color", dest="other")
        def run(color: bool = False, other: str = ""):
            raise AssertionError

        with self.assertRaises(DefinitionError):
            app.invoke(["--help"])

    def test_module_main_default_name(self):
        from expose_interface import get_interface

        self.assertEqual(get_interface(module="__main__").name, "main")

    def test_explicit_converters_preserve_python_string_defaults(self):
        calls = []

        def convert(value):
            calls.append(value)
            return value.upper()

        app = Interface("app")

        @app.program
        @option("--value", type=convert)
        def run(value: str = "lower"):
            return value

        @app.program
        @argument("value", type=convert, choices=["lower", "OTHER"])
        def positional(value: str = "lower"):
            return value

        self.assertEqual(app.invoke(["run"]), run())
        self.assertEqual(app.invoke(["positional"]), positional())
        self.assertEqual(calls, [])
        self.assertEqual(app.invoke(["run", "--value", "chosen"]), "CHOSEN")
        self.assertEqual(app.invoke(["positional", "other"]), "OTHER")
        self.assertEqual(calls, ["chosen", "other"])
