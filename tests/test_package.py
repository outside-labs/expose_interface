"""Public package and process-level entry point checks."""

import subprocess
import sys
import unittest

from expose_interface import CommandError, DefinitionError, UsageError


class PackageTests(unittest.TestCase):
    def test_error_boundaries_are_distinct(self):
        self.assertTrue(issubclass(DefinitionError, ValueError))
        self.assertTrue(issubclass(UsageError, ValueError))
        self.assertFalse(issubclass(CommandError, ValueError))

    def test_module_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "expose_interface", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Export ordinary Python functions", result.stdout)

    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "expose_interface", "--version"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "expose-interface 0.1.0")
