"""Registration is explicit and preserves ordinary Python behavior."""

from dataclasses import FrozenInstanceError
import unittest
from uuid import uuid4

from expose_interface import (
    DefinitionError, Interface, argument, arguments, cli, command, expose,
    flag, get_interface, interface, option, program,
)


class DeclarationTests(unittest.TestCase):
    def test_original_callable_and_metadata_in_both_orders(self):
        app = Interface("app")

        @option("--count", "-n")
        @app.program
        @argument("value")
        def add_value(value: int, count: int = 1):
            """Add a value."""
            return value + count

        self.assertEqual(add_value(2, count=3), 5)
        record, = app.programs
        self.assertIs(record.function, add_value)
        self.assertEqual(record.name, "add-value")
        self.assertEqual({p.dest for p in record.parameters}, {"count", "value"})
        with self.assertRaises(FrozenInstanceError):
            record.name = "other"

    def test_inline_and_plural_declarations(self):
        for metadata in (dict(argument="first"), dict(arguments=["first", "second"])):
            app = Interface("app")
            app.program(lambda first, second: None, name="run", **metadata)
            self.assertEqual([p.dest for p in app.programs[0].parameters], list(metadata.values())[0] if "arguments" in metadata else ["first"])
        app = Interface("app")

        @app.program
        @arguments("first", "second")
        def run(first, second):
            return first, second

        self.assertEqual(run(1, 2), (1, 2))

    def test_default_is_distinct_from_inferred_name(self):
        app = Interface("app")
        app.program(lambda: None, name=None)
        app.program(lambda: None, name="run")
        self.assertEqual([p.name for p in app.programs], [None, "run"])
        with self.assertRaises(DefinitionError):
            app.program(lambda: None, name=None)

    def test_duplicates_reserved_help_and_conflicts(self):
        app = Interface("app")
        app.program(lambda: None, name="run")
        with self.assertRaises(DefinitionError):
            app.program(lambda: None, name="run")
        for switches in (("--help",), ("-h",), ("bad",), ("--ok", "--ok")):
            with self.subTest(switches=switches), self.assertRaises(DefinitionError):
                option(*switches)
        with self.assertRaises(DefinitionError):
            argument("not-valid")
        with self.assertRaises(DefinitionError):
            flag("--all", multiple=True)
        with self.assertRaises(DefinitionError):
            arguments("a", "a")(lambda a: None)
        with self.assertRaises(DefinitionError):
            app.program(argument("a")(lambda a: None), name="other", argument="a")

    def test_module_registry_and_duplicate_declaration(self):
        owner = f"test_{uuid4().hex}"
        app = interface("tools", module=owner)
        self.assertIs(get_interface("tools", module=owner), app)
        with self.assertRaises(DefinitionError):
            interface("tools", module=owner)
        with self.assertRaises(DefinitionError):
            get_interface("unknown", module=owner)
        self.assertIs(get_interface(module=owner), get_interface(module=owner))

    def test_module_program_and_aliases(self):
        def run():
            return "ok"

        run.__module__ = f"test_{uuid4().hex}"
        self.assertIs(program(run), run)
        self.assertIs(get_interface(module=run.__module__).programs[0].function, run)
        self.assertIs(expose, program)
        self.assertIs(command, program)
        self.assertIs(cli, program)
        self.assertIs(Interface.cli, Interface.program)

    def test_bound_method_and_mounts(self):
        class Tool:
            def run(self, value: int):
                return value * 2

        root, child = Interface("app"), Interface("tools")
        child.program(Tool().run)
        root.add_interface(child)
        self.assertEqual(child.programs[0].function(3), 6)
        with self.assertRaises(DefinitionError):
            root.program(lambda: None, name="tools")
        with self.assertRaises(DefinitionError):
            child.add_interface(root)
        root.children.clear()
        self.assertIn("tools", root.children)

    def test_invalid_names_and_metadata(self):
        for name in ("", ".", "--oops", "a b"):
            with self.subTest(name=name), self.assertRaises(DefinitionError):
                Interface(name)
        app = Interface("app")
        for metadata in (dict(arguments="a"), dict(arguments=["a", "a"]), dict(argument="a", arguments=["b"]), dict(order=True)):
            with self.subTest(metadata=metadata), self.assertRaises(DefinitionError):
                app.program(lambda a: None, name="run", **metadata)
