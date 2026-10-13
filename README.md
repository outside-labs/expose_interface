# expose_interface

Export ordinary Python functions and bound methods as command line programs.
The package uses the standard library and supports Python 3.11 and later.

## Define an interface

```python
from expose_interface import Interface, argument, flag, option

app = Interface("hello", description="Greeting programs.")

@app.program
@argument("name")
@option("--count", "-n", help="Number of greetings.")
@flag("--color", "-G", help="Enable color.")
def greet(name: str, *, count: int = 1, color: bool = False):
    """Greet someone a chosen number of times."""
    for _ in range(count):
        print(f"Hello, {name}!")

main = app.main
```

Decorators register metadata and return the original function. Ordinary calls
such as `greet("World", count=2)` continue to work. Required positional
parameters are inferred as arguments, defaults and keyword-only parameters as
options, and Boolean options as flags. Decorators supply aliases and help or
override that classification. They can appear above or below `@app.program`.

The program name defaults to the function name with underscores changed to
hyphens. Use `@app.program(name=None)` for a program invoked at the bare
interface name. A default with positional arguments must have its own interface
to keep those inputs distinct from subcommand names.

## Run from a module or install a shell command

For a source module named `hello.py` in the current directory:

```sh
python -m expose_interface hello:app greet World -n 2
python -m expose_interface hello:app --help
python -m expose_interface hello:app greet --help
```

The launcher imports only the explicitly requested module. For installed,
importable modules, the `expose-interface hello:app ...` console command also
works. For current-directory source files, `python -m` places that directory on
Python's import path.

Export the application's own executable through its `pyproject.toml`:

```toml
[project.scripts]
hello = "hello:main"
hi = "hello:main"
```

After installing that application, its environment's `bin` directory (Scripts
on Windows) contains both commands. Both invoke the same interface. The library
does not write executables elsewhere on the system. No distribution has been
published yet; development consumers can install this source checkout.

## Arguments, options and flags

These positional declarations are equivalent:

```python
@app.program(arguments=["first", "second"])
def combine(first: str, second: str): ...

# Alternatively: @arguments("first", "second") below or above @app.program.
# One parameter: @app.program(argument="first") or @argument("first").
```

Scalar inputs support `str`, `int`, `float`, `Path`, `Enum` values and `Literal`
choices. Nullable options use `T | None`. Collections use `list[T]` or
`tuple[T, ...]`: positional collections consume multiple tokens, and option
collections accept repeated switches. An explicit `type=` supplies a custom
converter. Variadic Python signatures and arbitrary unions/models fail clearly.

```python
@app.program
@option("--plugin", dest="plugins", multiple=True)
def inspect_plugins(plugins: tuple[str, ...] = ()):
    print(plugins)
```

Flags support `--flag` and `--no-flag`. A callback configures another concern
after parsing and before the program:

```python
def configure_color():
    print("Color selected")

@app.program
@flag("--color", "-G", mtd=configure_color)
def display(color: bool = False): ...
```

Callbacks accept no required arguments and run only when the positive flag is
explicitly selected. Bound methods can use `mtd=True` to resolve the flag's
destination on their instance, or `mtd="method_name"` to choose a method.

## Nested commands and invocation context

```python
from expose_interface import Context

def setup(context: Context, verbose: bool = False):
    context.obj = {"verbose": verbose}

root = Interface("tools", setup=setup)
files = Interface("files", description="File programs.")
root.add_interface(files)

@files.program
def show(context: Context, path: str):
    print(context.obj, path)

root.invoke(["--verbose", "files", "show", "notes.md"])
```

`Context` is injected and is never a CLI argument. Each invocation has fresh
state. Parent options precede the child name; child options follow their command
name. Help and invalid input never execute setup, flag callbacks or programs.
Sync and async setup/callbacks/programs are supported. Use `await app.invoke_async`
inside an existing event loop; `app.invoke` runs from synchronous Python.

`invoke` returns the callable's result without printing it. `main` is the shell
boundary: success exits 0, `UsageError` exits 2 and expected `CommandError` exits 1.
Unexpected exceptions keep their traceback. Functions print/serialize their own
output; integer return values are not shell exit codes.

## Help and configuration

`-h` and `--help` show full cleaned program docstrings. Interface help shows its
description and alphabetical program summaries. Set `order=0` to put a program
first within its section, and `section="Files"` to group it. Child mounts accept
the same `order` and `section` fields. Sections sort alphabetically; ungrouped
programs come first. Default-program docstrings appear in interface help too.

```toml
[tool.expose-interface]
name = "hello"
description = "Greeting programs."
```

Load a specific file with `Interface.from_toml("pyproject.toml")`. Configuration
never searches directories or imports commands. `app.format_help()` renders
help without executing user code.

For module-level decorators, `@program(interface=".")` registers on the defining
module's default interface; `get_interface().main` exports it. Declare a named
module interface with `interface("tools")`; duplicate declarations in that
module raise `DefinitionError`. The `program`, `expose`, `command` and `cli`
decorators are aliases. [API details](docs/API.md) describe validation and defaults.

## Development

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv build
```

The development interpreter is Python 3.14. CI tests the supported Python floor
and current interpreter on Linux, plus Windows and macOS. Distribution checks
build a wheel/source archive and exercise an installed wheel outside the checkout.

Releases and package publication are separate from source development.

The [design and task queue](https://github.com/outside-labs/expose_interface/issues/1)
tracks the initial contract and Hidden Moves adoption.
