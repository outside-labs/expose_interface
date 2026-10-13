"""Invocation-local context and sync/async execution."""

import asyncio
from dataclasses import dataclass
import inspect
import sys
from typing import Any

from .errors import CommandError, UsageError


@dataclass
class Context:
    """State shared by setup and the selected command for one invocation."""

    obj: Any = None
    command: str | None = None
    path: tuple[str, ...] = ()


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


async def execute(plan, namespace):
    context = Context(command=plan.program.record.name, path=plan.path)
    for step in (*plan.setups, plan.program):
        values = {}
        positional = []
        for binding in step.bindings:
            value = context if binding.injected else binding.value(namespace)
            if binding.parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(value)
            else:
                values[binding.parameter.name] = value
            if binding.callback and binding.key in getattr(namespace, "_expose_selected_flags", set()):
                await _resolve(binding.callback())
        result = await _resolve(step.record.function(*positional, **values))
    return result


def invoke(app, argv=None, *, prog_name=None):
    from .parsing import prepare

    prepared = prepare(app, argv, prog_name=prog_name)
    if prepared is None:
        return None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute(*prepared))
    raise RuntimeError("Use await interface.invoke_async() inside a running event loop.")


async def invoke_async(app, argv=None, *, prog_name=None):
    from .parsing import prepare

    prepared = prepare(app, argv, prog_name=prog_name)
    return None if prepared is None else await execute(*prepared)


def main(app, argv=None, *, prog_name=None):
    try:
        invoke(app, argv, prog_name=prog_name)
    except UsageError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
    except CommandError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    # Return values are Python values, never implicit shell status codes.
    raise SystemExit(0)
