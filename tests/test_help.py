"""Help rendering, explicit configuration and process-level module dispatch."""

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from expose_interface import DefinitionError, Interface, option


class HelpTests(unittest.TestCase):
    def capture(self, app, argv):
        output = StringIO()
        with redirect_stdout(output):
            app.invoke(argv)
        return output.getvalue()

    def test_sorted_program_summaries_and_full_docstring(self):
        app = Interface("demo", description="Description from the interface.")

        @app.program
        def zebra():
            """Zebra summary.

            A second paragraph with 100% detail.
            """

        @app.program
        def alpha():
            """Alpha summary."""

        help_text = app.format_help()
        self.assertIn("demo", help_text)
        self.assertIn(app.description, help_text)
        self.assertLess(help_text.index("alpha"), help_text.index("zebra"))
        self.assertNotIn("second paragraph", help_text)
        full = self.capture(app, ["zebra", "--help"])
        self.assertIn("Zebra summary.\n\nA second paragraph with 100% detail.", full)
        self.assertEqual(full, self.capture(app, ["zebra", "-h"]))

    def test_manual_order_and_section_grouping(self):
        root, child = Interface("app"), Interface("tools", description="Tool group.")
        root.add_interface(child, section="Utilities", order=0)
        root.program(lambda: None, name="zebra", order=0)
        root.program(lambda: None, name="alpha")
        root.program(lambda: None, name="files", section="Utilities", order=1)
        text = root.format_help()
        self.assertLess(text.index("zebra"), text.index("alpha"))
        self.assertIn("Utilities:", text)
        self.assertLess(text.index("tools"), text.index("files"))

    def test_nested_and_default_help(self):
        root = Interface("app", description="Root description.")
        child = Interface("child", description="Child description.")
        root.add_interface(child)

        @child.program(name=None)
        def run():
            """Full default program documentation."""

        text = self.capture(root, ["child", "--help"])
        self.assertIn("app child", text)
        self.assertIn("Child description.", text)
        self.assertIn("Full default program documentation.", text)

    def test_literal_percent_option_help(self):
        app = Interface("app")

        @app.program
        @option("--value", help="Accept 100% of the input, including %(text)s.")
        def run(value: str = ""):
            pass

        self.assertIn("100% of the input, including %(text)s.", self.capture(app, ["run", "--help"]))

    def test_toml_configuration_and_failures(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "interface.toml"
            path.write_text('[tool.expose-interface]\nname = "configured"\ndescription = "From TOML."\n')
            app = Interface.from_toml(path)
            self.assertIn("From TOML.", app.format_help())
            self.assertEqual(app.name, "configured")
            for content in ('broken=', '[tool.expose-interface]\nname=5', '[tool.expose-interface]\nname="app"\ndescription=5', '[tool.expose-interface]\nname="app"\nunknown=true', '[other]\nname="app"'):
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(DefinitionError):
                        Interface.from_toml(path)
            with self.assertRaises(DefinitionError):
                Interface.from_toml(path.with_name("missing.toml"))

    def test_module_launcher_explicit_and_default_interfaces(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "fixture_cli.py").write_text('''from expose_interface import Interface, program
app = Interface("fixture", description="Selected fixture.")
@app.program
def echo(value: int):
    print(value + 1)
@program(name=None)
def root():
    print("default module interface")
''')
            environment = dict(os.environ, PYTHONPATH=directory)
            for target, arguments, expected in (("fixture_cli:app", ["echo", "3"], "4"), ("fixture_cli", [], "default module interface")):
                result = subprocess.run([sys.executable, "-m", "expose_interface", target, *arguments], cwd=directory, env=environment, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
            result = subprocess.run([sys.executable, "-m", "expose_interface", "fixture_cli:app", "echo", "--help"], cwd=directory, env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fixture echo", result.stdout)
            for target, arguments in (("fixture_cli:missing", []), ("nonexistent_expose_fixture", []), ("fixture_cli:app", ["echo", "bad"]), ("./fixture_cli.py", [])):
                result = subprocess.run([sys.executable, "-m", "expose_interface", target, *arguments], cwd=directory, env=environment, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_launcher_preserves_import_programming_errors(self):
        with TemporaryDirectory() as directory:
            Path(directory, "broken_cli.py").write_text("import nonexistent_internal_expose_dependency\n")
            result = subprocess.run([sys.executable, "-m", "expose_interface", "broken_cli"], cwd=directory, env=dict(os.environ, PYTHONPATH=directory), text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Traceback", result.stderr)
            self.assertIn("nonexistent_internal_expose_dependency", result.stderr)
