# Hidden Moves adoption

The [adapter example](../examples/hidden_moves_cli.py) exercises the current
Hidden Moves public API without importing Click. It preserves `moves list`,
`moves show`, `moves call`, `plugins list`, repeated `--plugin` options and JSON
input/output. Malformed JSON fails during parsing before provider setup.

The conformance suite is separate from core tests and uses a real consumer
checkout. The initial baseline is outside-labs/hidden_moves revision
`6fa99794301efcce34cbed56e7c7b7eef162a184`.

```sh
PYTHONPATH="examples:/path/to/hidden_moves/src" \
  uv run python -m unittest discover -s consumer_tests -v
PYTHONPATH="/path/to/hidden_moves/src" \
  uv run python -m expose_interface examples.hidden_moves_cli:app moves list --json
```

For Windows, set `PYTHONPATH` with the shell's environment syntax and use a
semicolon between paths. The consumer's source path is used directly; core
verification never installs Hidden Moves or its Click dependency. CI pins the
consumer checkout and tests the adapter against an installed expose-interface
wheel on Python 3.11/3.14.

To verify ordinary application entry points, `scripts/check_distribution.py`
builds the library and a temporary synthetic consumer, installs their wheels,
and exercises both consumer executable aliases outside their source trees.

```sh
uv run python scripts/check_distribution.py --hidden-moves /path/to/hidden_moves
```

This also runs the actual consumer conformance suite against the installed wheel.

## Consumer migration

The actual Hidden Moves checkout has not been changed. After agreeing on a
dependency delivery path and authorizing its edit:

1. Move the adapter into `hidden_moves.cli` and keep both existing scripts
   pointing to `hidden_moves.cli:main`.
2. Replace Click test-runner use with stdout/stderr capture and `main(argv)`
   exit checks. Keep provider/capability contracts and public command names.
3. Add the agreed expose-interface dependency and remove Click, updating its
   lockfile and usage documentation.
4. Run the consumer's core, interoperability and installed-wheel/release checks.
5. Merge the consumer PR only after its CI passes.

Python 3.11 remains supported. Provider state is fresh for each invocation,
help does not activate providers, and async results are awaited. Publication
of expose-interface is tracked separately from this source-level verification.
