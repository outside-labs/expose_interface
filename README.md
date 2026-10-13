# expose_interface

Export ordinary Python functions and bound methods as command line programs.
The package uses the standard library and supports Python 3.11 and later.

The initial implementation is tracked in the [design and task queue](https://github.com/outside-labs/expose_interface/issues/1).

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
