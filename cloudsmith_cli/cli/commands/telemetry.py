# Copyright 2026 Cloudsmith Ltd
"""CLI - Telemetry command group: see and control usage telemetry."""

import click

from ...core import telemetry_common
from ...core.usage import identity, settings, state
from .. import command, decorators, usage_capture, utils

# Not `from .. import telemetry`: this module defines the `telemetry` group.
from ..telemetry import ERRORS, send
from .main import main

_DISABLED = telemetry_common.Mode.DISABLED.value


def _usage_status(opts, typed=()):
    """The usage reporting status and the reason for it.

    Same gates, same order, as core/usage/run.py::_finish, so status never
    says "enabled" for a run that would send nothing.
    """
    mode, source = telemetry_common.resolve_mode(telemetry_common.Kind.USAGE)
    if mode is telemetry_common.Mode.DISABLED:
        return _DISABLED, source
    # status itself runs initialise_session, so opts holds the resolved host.
    host = usage_capture.resolve_api_host(opts, resolved=True)
    if not telemetry_common.is_cloudsmith_host(host):
        return _DISABLED, "non-Cloudsmith API host"
    # Typed spellings too, as collect_facts does: `-S` disables sending even
    # when a later `--ssl-verify` wins for the command itself.
    if not usage_capture.resolve_ssl_verify(opts, typed):
        return _DISABLED, "SSL verification off"
    if (
        telemetry_common.get_environment() == "development"
        and not settings.override_set()
    ):
        return _DISABLED, "development build"
    # run.py logs the payload to stderr and never sends in log mode.
    if mode is not telemetry_common.Mode.LOG and not settings.project_key():
        return _DISABLED, "no endpoint key"
    return mode.value, source


def _error_status():
    """The error reporting status and the reason for it.

    Same rules as core/telemetry.py::report_exception: none of the usage
    gates, and log mode needs no DSN.
    """
    from ...core import telemetry as error_reporting

    mode, source = telemetry_common.resolve_mode(telemetry_common.Kind.ERRORS)
    if mode is telemetry_common.Mode.ENABLED and not error_reporting.get_dsn():
        return _DISABLED, "no DSN"
    return mode.value, source


@main.group(cls=command.AliasGroup)
# Manages telemetry itself: report crashes, never usage.
@send(ERRORS)
def telemetry():
    """See and control pseudonymous usage telemetry."""


@telemetry.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_session
@click.pass_context
def status(ctx, opts):
    """Show whether usage and error reporting are enabled, disabled or logging, and why."""
    usage, usage_reason = _usage_status(opts, usage_capture.typed_flags(ctx.meta))
    errors, errors_reason = _error_status()
    data = {
        "usage_reporting": {
            "status": usage,
            "reason": usage_reason,
            "endpoint": settings.host(),
        },
        "error_reporting": {"status": errors, "reason": errors_reason},
        "install_id_enabled": settings.install_id_enabled(),
    }
    if not utils.maybe_print_as_json(opts, data):
        click.echo(f"Usage reporting: {usage} ({usage_reason})")
        click.echo(f"Error reporting: {errors} ({errors_reason})")
        click.echo(f"Install ID: {'on' if data['install_id_enabled'] else 'off'}")


@telemetry.command(name="id")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def show_id(ctx, opts):  # pylint: disable=unused-argument
    """Show the install ID, if one is stored."""
    install_id = state.read().get("install_id")
    if not utils.maybe_print_as_json(opts, {"install_id": install_id}):
        click.echo(install_id or "none")


@telemetry.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def reset(ctx, opts):  # pylint: disable=unused-argument
    """Delete the install ID; a new one is created on the next command."""
    try:
        identity.reset()
    except identity.IdentityResetError as exc:
        # Raised, not ctx.exit(1): the command's main() returns an Exit code
        # instead of raising SystemExit, which CliRunner would report as 0.
        raise click.ClickException(str(exc)) from exc
    if not utils.maybe_print_as_json(opts, {"deleted": True}):
        click.echo("Install ID deleted. A new one is created on the next command.")
