# API reference

## Interface ownership

`Interface(name, description="", setup=None)` creates an independent interface.
Names contain letters, digits, hyphens or underscores, beginning with a letter
or digit. `setup` is a callable that runs only after successful command parsing.

`app.program(function=None, name=<inferred>, argument=None, arguments=None,
order=None, section=None)` registers a callable and returns it unchanged. It
supports `@app.program`, `@app.program(...)` and `app.program(instance.method)`.
`app.command`, `app.expose` and `app.cli` are aliases. Explicit `name=None` selects
the bare/default program; omitting `name` infers the function's hyphenated name.

`add_interface(child, name=None, order=None, section=None)` mounts a child under
its name or an explicit name. Cycles and duplicate command/default/mount names
raise `DefinitionError`. `programs` returns immutable records and `children`
returns a copy of the mounts.

`interface(name, description="", setup=None, module=None)` declares one named
interface for the calling module. Repeating the same name in the same module
raises `DefinitionError`. `get_interface(name=".", module=None)` resolves it;
the default is created lazily. The module-level `program` decorator accepts an
`Interface` instance or a module interface name. Module registry lookup follows
the callable's defining module, so an imported function retains its owner.
Use independent `Interface` objects for independent applications and tests.

## Parameter declarations

| Declaration | Behavior |
| --- | --- |
| `argument("path", **fields)` | Positional input for the Python parameter `path` |
| `arguments("first", "second")` | Several positional declarations |
| `option("--name", "-n", dest=None, **fields)` | Named input that consumes a value |
| `flag("--color", "-G", dest=None, mtd=False, **fields)` | Boolean input with an optional callback |

`dest` defaults to the first long switch, with hyphens changed to underscores,
or the short switch when no long one exists. Supply `dest` when shell and Python
names differ. `-h` and `--help` are reserved. Every declaration must map to a
signature parameter; duplicate declarations and overlapping switches fail.
Generated `--no-flag` switches also participate in conflict detection.

Fields are `type`, `default`, `required`, `multiple`, `nargs`, `choices` and
`help`. Explicit values override signature inference. `choices` contains the
converted Python values, such as integers or Enum instances. Unknown fields
raise `DefinitionError`.

- `type` accepts a supported scalar/collection annotation or an explicit
  string-to-value converter. Custom converters should raise `ValueError`,
  `TypeError` or `argparse.ArgumentTypeError` on invalid input.
- Defaults are already Python values; supported built-in/Enum/Literal defaults
  must match their declared type. Nullable annotations permit `None`. Omitted
  optional inputs use the declared default. Collection defaults are copied;
  explicitly supplied repeated options replace that default.
- `multiple=True` accepts repeated value options and returns a list, or a tuple
  for a tuple-annotated parameter. Collection annotations infer repetition for
  options without needing this field.
- Collection positional inputs infer `nargs="+"` when required and `"*"` when
  defaulted. Collection value options can use `nargs="+"`, `"*"` or an integer
  instead of repetition. Scalar positional inputs can use `"?"` when optional;
  scalar options with `"?"` require a nullable annotation. A required positional
  input cannot use optional nargs. `multiple` and explicit nargs cannot combine.
- Flags require Boolean parameters/defaults and reject choices, repetition and
  nargs. Positive/negative long switches set True/False; short switches select
  True. Callbacks run once for the final selected positive value and do not
  replace the Boolean argument. A callback may be async.

Types: `str`, `int`, `float`, `pathlib.Path`, Enum values, string/integer/float
`Literal` choices, nullable scalar/collection options, `list[T]` and
`tuple[T, ...]`. Nested collections, fixed heterogeneous tuples, Boolean
collections, arbitrary unions and models are unsupported. Unannotated required
inputs default to strings; scalar defaults infer their type. Empty unannotated
list/tuple defaults infer string elements. Add annotations for other elements.

## Parsing and execution

`invoke(argv=None, prog_name=None)` parses an explicit token sequence or
`sys.argv[1:]`, runs the selected command and returns its result. Setup receives
its own signature-derived inputs; parent switches precede the child command
name. The whole tree is compiled before parsing. Unsupported definitions fail
as `DefinitionError`, even when help was requested.

`invoke_async` has the same contract inside an existing event loop. Sync invoke
uses an event loop for async results and rejects use inside an active loop with
a message directing the caller to `invoke_async`. Custom awaitable results are
supported alongside coroutine functions.

An input annotated `Context` receives `Context(obj=None, command=None, path=())`.
It is shared by the selected path's setup functions and program for that one
invocation. `command` is the selected program's name; `path` contains mounted
command names. Setup return values are ignored. Set `context.obj` for state.
Context parameters cannot have argument/option metadata.

`main` exits 0 on success/help, 2 for `UsageError` and 1 for `CommandError`.
Only those expected errors are converted to terminal diagnostics. Return values
do not become exit codes or stdout; serialize or print explicitly in commands.
Calling a tree without a selected/default program displays that node's help.

## Help, TOML and exporting

`format_help(prog_name=None)` renders root help. Root/default and leaf docstrings
use `inspect.getdoc` cleaning; paragraphs are preserved. Program summaries use
the first line. Sections sort alphabetically, ungrouped programs first; within
a section, explicit integer orders precede unordered names, with alphabetical
tie-breaking. Mounted interfaces participate in the same presentation rules.

`Interface.from_toml(path, table="tool.expose-interface", setup=None)` requires
one explicit file/table containing `name` and optional `description`. Extra
keys, invalid field types, unreadable files and malformed TOML fail as
`DefinitionError`. There is no configuration search or import discovery.

`python -m expose_interface MODULE[:INTERFACE] [ARGS...]` imports the selected
module and resolves an explicit Interface attribute or the module's default
registry. The installed `expose-interface` launcher requires its target module
to be importable; use `python -m` for current-directory sources. Missing modules
or invalid selectors are usage errors. A module's internal import failures keep
their traceback.

Standard `[project.scripts]` entries point to `package.module:main`, where
`main = app.main`. Package installation creates executables and permits several
shell aliases. The library does not alter system shell paths or install scripts
independently of Python packaging.
