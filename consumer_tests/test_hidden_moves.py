"""Conformance against the real Hidden Moves API; run separately from core tests."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.metadata import EntryPoint
from io import StringIO
import json
import sys
import unittest
from unittest.mock import patch

from hidden_moves import ENTRY_POINT_GROUP, MoveSpec
import hidden_moves_cli as cli


class HiddenMovesTests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            cli.main(arguments)
        return caught.exception.code, output.getvalue(), error.getvalue()

    @contextmanager
    def provider(self, *specs):
        entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
        with patch.object(cli, "discover_providers", return_value=(entry,)), patch.object(EntryPoint, "load", return_value=lambda: specs):
            yield

    def test_adapter_does_not_import_click(self):
        self.assertNotIn("click", sys.modules)

    def test_help_and_empty_listing_do_not_discover_providers(self):
        with patch.object(cli, "discover_providers") as discover:
            for arguments in (["--help"], ["moves", "--help"], ["moves", "call", "-h"], ["moves", "list"]):
                result = self.invoke(arguments)
                self.assertEqual(result[0], 0, result[2])
            discover.assert_not_called()
        self.assertEqual(result[1], "")
        self.assertEqual(json.loads(self.invoke(["moves", "list", "--json"])[1]), [])
        self.assertEqual(set(cli.app.children), {"moves", "plugins"})

    def test_unknown_domain_commands_and_invalid_json_are_usage_errors(self):
        for name in ("text", "json", "cmd", "notes"):
            self.assertEqual(self.invoke([name])[0], 2)
        for value in ("{broken", "[]"):
            with patch.object(cli, "discover_providers") as discover:
                status, _, error = self.invoke(["--plugin", "example", "moves", "call", "unknown", "--arguments", value])
            self.assertEqual(status, 2)
            self.assertIn("Invalid value", error)
            discover.assert_not_called()

    def test_unknown_move_is_expected_runtime_error(self):
        status, _, error = self.invoke(["moves", "show", "unknown"])
        self.assertEqual(status, 1)
        self.assertIn("Unknown move", error)

    def test_target_binding_is_reported_without_execution(self):
        def operation(target: str, value: str) -> str:
            raise AssertionError("inspection executed a capability")

        with self.provider(MoveSpec("operation", operation, bind_target=True)):
            status, output, error = self.invoke(["--plugin", "example", "moves", "show", "operation"])
        self.assertEqual(status, 0, error)
        self.assertFalse(json.loads(output)["available"])
        self.assertTrue(json.loads(output)["bind_target"])

    def test_json_listing_reports_schema_without_execution(self):
        def operation(value: str) -> str:
            raise AssertionError("listing executed a capability")

        with self.provider(MoveSpec("operation", operation)):
            status, output, error = self.invoke(["--plugin", "example", "moves", "list", "--json"])
        self.assertEqual(status, 0, error)
        definitions = json.loads(output)
        self.assertEqual([item["name"] for item in definitions], sorted(item["name"] for item in definitions))
        definition = next(item for item in definitions if item["name"] == "operation")
        self.assertEqual(definition["input_schema"]["required"], ["value"])

    def test_call_returns_serialized_capability_result(self):
        def operation(value: str) -> str:
            return value.upper()

        with self.provider(MoveSpec("operation", operation)):
            status, output, error = self.invoke(["--plugin", "example", "moves", "call", "operation", "--arguments", '{"value":"Hello World"}'])
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), "HELLO WORLD")

    def test_invalid_schema_arguments_fail_before_capability_execution(self):
        def operation(value: str) -> str:
            raise AssertionError("invalid arguments executed")

        with self.provider(MoveSpec("operation", operation)):
            for arguments in ("{}", '{"value":1}', '{"value":"ok","extra":1}'):
                with self.subTest(arguments=arguments):
                    status, _, error = self.invoke(["--plugin", "example", "moves", "call", "operation", "--arguments", arguments])
                    self.assertEqual(status, 1)
                    self.assertNotIn("invalid arguments executed", error)

    def test_missing_binding_is_expected_error(self):
        def operation(target: str) -> str:
            return target

        with self.provider(MoveSpec("operation", operation, bind_target=True)):
            status, _, error = self.invoke(["--plugin", "example", "moves", "call", "operation"])
        self.assertEqual(status, 1)
        self.assertIn("requires Moves", error)

    def test_async_capability_result_is_awaited(self):
        async def add(value: int) -> int:
            return value + 1

        with self.provider(MoveSpec("add", add)):
            status, output, error = self.invoke(["--plugin", "example", "moves", "call", "add", "--arguments", '{"value":2}'])
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), 3)

    def test_capability_failure_has_terminal_error(self):
        def failure() -> None:
            raise RuntimeError("example failure")

        with self.provider(MoveSpec("failure", failure)):
            status, _, error = self.invoke(["--plugin", "example", "moves", "call", "failure"])
        self.assertEqual(status, 1)
        self.assertIn("example failure", error)

    def test_plugin_listing_reads_metadata_without_loading(self):
        entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
        with patch.object(cli, "discover_providers", return_value=(entry,)), patch.object(EntryPoint, "load") as load:
            status, output, error = self.invoke(["plugins", "list"])
        self.assertEqual(status, 0, error)
        self.assertIn("example:provide", output)
        load.assert_not_called()

    def test_loaded_providers_are_isolated_per_invocation(self):
        with self.provider(MoveSpec("upper", str.upper)):
            status, output, error = self.invoke(["--plugin", "example", "moves", "show", "upper"])
            self.assertEqual(status, 0, error)
            self.assertEqual(json.loads(output)["source"], "example:provide")
            self.assertEqual(self.invoke(["moves", "show", "upper"])[0], 1)

    def test_missing_ambiguous_and_failed_providers_are_expected_errors(self):
        entry = EntryPoint("example", "example:provide", ENTRY_POINT_GROUP)
        other = EntryPoint("example", "other:provide", ENTRY_POINT_GROUP)
        for entries in ((), (entry, other)):
            with patch.object(cli, "discover_providers", return_value=entries), patch.object(EntryPoint, "load") as load:
                self.assertEqual(self.invoke(["--plugin", "example", "moves", "list"])[0], 1)
                load.assert_not_called()
        with patch.object(cli, "discover_providers", return_value=(entry,)), patch.object(EntryPoint, "load", side_effect=RuntimeError("provider broken")):
            status, _, error = self.invoke(["--plugin", "example", "moves", "list"])
        self.assertEqual(status, 1)
        self.assertIn("provider broken", error)

    def test_repeated_plugin_option_loads_two_distinct_providers(self):
        first = EntryPoint("first", "first:provide", ENTRY_POINT_GROUP)
        second = EntryPoint("second", "second:provide", ENTRY_POINT_GROUP)

        def one(value: str) -> str:
            return value

        def two(value: int) -> int:
            return value

        with patch.object(cli, "discover_providers", return_value=(first, second)), patch.object(EntryPoint, "load", side_effect=[lambda: (MoveSpec("one", one),), lambda: (MoveSpec("two", two),)]):
            status, output, error = self.invoke(["--plugin", "first", "--plugin", "second", "moves", "list", "--json"])
        self.assertEqual(status, 0, error)
        self.assertEqual([item["name"] for item in json.loads(output)], ["one", "two"])
