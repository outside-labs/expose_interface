"""Build and verify installed library/consumer wheels outside their source trees."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def run(*command, cwd, environment, status=0, output=None):
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True)
    if result.returncode != status or (output is not None and output not in result.stdout):
        raise RuntimeError(f"Command failed: {command!r}\nstatus={result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidden-moves", type=Path, help="Optional actual consumer checkout for installed-wheel conformance.")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("Install the project's uv development/build tool first.")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    with TemporaryDirectory(prefix="expose-distribution-") as directory:
        temporary = Path(directory)
        library_dist = temporary / "library-dist"
        run(uv, "build", str(root), "--out-dir", str(library_dist), cwd=temporary, environment=environment)
        if not list(library_dist.glob("*.tar.gz")):
            raise RuntimeError("Missing source distribution.")
        consumer = temporary / "consumer"
        source = consumer / "src" / "fixture_consumer"
        source.mkdir(parents=True)
        (consumer / "pyproject.toml").write_text('''[project]
name = "fixture-consumer"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = ["expose-interface==0.1.0"]
[project.scripts]
expose-fixture = "fixture_consumer:main"
ef = "fixture_consumer:main"
[build-system]
requires = ["uv_build>=0.12.19,<0.13.0"]
build-backend = "uv_build"
''')
        (source / "__init__.py").write_text('''from expose_interface import CommandError, Interface, flag
app = Interface("fixture", description="Installed consumer interface.")
@app.program(name=None)
def root():
    print("ready")
@app.program
def echo(value: int):
    print(value + 1)
@app.program
def fail():
    raise CommandError("fixture failed")
@app.program
@flag("--color", mtd=lambda: print("color selected"))
def show(value: int, color: bool = False):
    print(value)
main = app.main
''')
        (source / "__main__.py").write_text("from . import main\nmain()\n")
        consumer_dist = temporary / "consumer-dist"
        run(uv, "build", str(consumer), "--out-dir", str(consumer_dist), cwd=temporary, environment=environment)
        wheel_env = temporary / "wheel-env"
        run(uv, "venv", str(wheel_env), "--python", sys.executable, cwd=temporary, environment=environment)
        binaries = wheel_env / ("Scripts" if os.name == "nt" else "bin")
        python = str(binaries / ("python.exe" if os.name == "nt" else "python"))
        wheels = [*library_dist.glob("*.whl"), *consumer_dist.glob("*.whl")]
        if len(wheels) != 2:
            raise RuntimeError("Expected one library wheel and one consumer wheel.")
        run(uv, "pip", "install", "--python", python, *map(str, wheels), cwd=temporary, environment=environment)
        run(uv, "pip", "check", "--python", python, cwd=temporary, environment=environment)
        run(python, "-I", "-c", "from pathlib import Path; from importlib.metadata import distribution; import expose_interface; import sys; assert not distribution('expose-interface').requires; assert not Path(expose_interface.__file__).is_relative_to(Path(sys.argv[1]))", str(root), cwd=temporary, environment=environment)
        run(python, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v", cwd=temporary, environment=environment)
        for name in ("expose-fixture", "ef"):
            command = str(binaries / (name + ".exe" if os.name == "nt" else name))
            run(command, cwd=temporary, environment=environment, output="ready")
            run(command, "--help", cwd=temporary, environment=environment, output="Installed consumer interface.")
            run(command, "echo", "4", cwd=temporary, environment=environment, output="5")
            failed = run(command, "fail", cwd=temporary, environment=environment, status=1)
            if "Error: fixture failed" not in failed.stderr:
                raise RuntimeError("Expected terminal failure diagnostic.")
            invalid = run(command, "show", "--color", "bad", cwd=temporary, environment=environment, status=2)
            if invalid.stdout or "Traceback" in invalid.stderr:
                raise RuntimeError("Invalid input executed a callback or leaked a traceback.")
        run(python, "-I", "-m", "fixture_consumer", "echo", "6", cwd=temporary, environment=environment, output="7")
        launch = str(binaries / ("expose-interface.exe" if os.name == "nt" else "expose-interface"))
        run(launch, "fixture_consumer:app", "echo", "7", cwd=temporary, environment=environment, output="8")
        if arguments.hidden_moves is not None:
            consumer_environment = dict(environment)
            consumer_environment["PYTHONPATH"] = os.pathsep.join((str(root / "examples"), str(arguments.hidden_moves.resolve() / "src")))
            run(python, "-m", "unittest", "discover", "-s", str(root / "consumer_tests"), "-v", cwd=temporary, environment=consumer_environment)
            run(launch, "hidden_moves_cli:app", "moves", "list", "--json", cwd=temporary, environment=consumer_environment, output="[]")
            print("Installed-wheel Hidden Moves conformance passed.")
        print("Wheel/sdist, installed core tests, consumer aliases, launcher and terminal errors passed.")


if __name__ == "__main__":
    main()
