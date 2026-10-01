# Copyright 2026 Cloudsmith Ltd
"""Report unexpected CLI errors, unless the user has opted out.

Only exceptions that escape every other handler reach here: click's own
errors and handled API errors never do. Reporting is on by default (including
in CI) and is turned off by either of:

* ``DO_NOT_TRACK`` - the cross-tool convention (https://consoledonottrack.com).
* ``CLOUDSMITH_NO_TELEMETRY`` - the tool-specific variable.

Reporting currently prints a marker line; it will become a Sentry event.
Keep this module's imports light: it is loaded on the error path only, and any
reporting SDK must be imported lazily inside :func:`report_exception`.
"""

import os

import click

NO_TELEMETRY_ENV = "CLOUDSMITH_NO_TELEMETRY"
DO_NOT_TRACK_ENV = "DO_NOT_TRACK"
OPT_OUT_ENVS = (DO_NOT_TRACK_ENV, NO_TELEMETRY_ENV)
_TRUTHY_ENV_VALUES = ("1", "true", "yes")


def format_exception_summary(exc: BaseException) -> str:
    """Return a one-line ``Type: message`` summary of ``exc``."""
    return f"{type(exc).__name__}: {exc}"


def telemetry_disabled(env: "os._Environ[str] | dict[str, str] | None" = None) -> bool:
    """Tell whether the user has opted out of error reporting.

    Either opt-out variable set to ``1``/``true``/``yes`` (case-insensitive)
    disables reporting. Any other value, or unset, leaves it on.
    """
    env = os.environ if env is None else env
    return any(
        env.get(name, "").strip().lower() in _TRUTHY_ENV_VALUES for name in OPT_OUT_ENVS
    )


def report_exception(exc: BaseException) -> bool:
    """Report ``exc`` unless opted out; return whether it was reported.

    Never raises: a failure while reporting must not change the outcome of
    the command that is already failing.
    """
    try:
        if telemetry_disabled():
            return False
        click.echo(f"oopsie! {format_exception_summary(exc)}", err=True)
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False
