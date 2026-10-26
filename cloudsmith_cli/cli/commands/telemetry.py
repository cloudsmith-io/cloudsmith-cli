# Copyright 2026 Cloudsmith Ltd
"""CLI - Telemetry command group: see and control usage telemetry."""

import os

import click

from ...core import telemetry_common
from ...core.usage import identity, settings, state
from .. import command, decorators, usage_capture, utils
from .main import main


def _reason(opts, typed=()):
    # Same gates, same order, as core/usage/run.py::_finish, so status never
    # says "on" for a run that would send nothing.
    for name in (telemetry_common.DO_NOT_TRACK_ENV, telemetry_common.NO_TELEMETRY_ENV):
        if telemetry_common.telemetry_disabled({name: os.environ.get(name, "")}):
            return name
    if telemetry_common.config_disabled():
        return "config"
    # status itself runs initialise_session, so opts holds the resolved host.
    host = usage_capture.resolve_api_host(opts, resolved=True)
    if not telemetry_common.is_cloudsmith_host(host):
        return "non-Cloudsmith API host"
    # Typed spellings too, as collect_facts does: `-S` disables sending even
    # when a later `--ssl-verify` wins for the command itself.
    if not usage_capture.resolve_ssl_verify(opts, typed):
        return "SSL verification off"
    if (
        telemetry_common.get_environment() == "development"
        and not settings.override_set()
    ):
        return "development build"
    if settings.log_mode():
        # run.py logs the payload to stderr and never sends in log mode.
        return "log only"
    if not settings.project_key():
        return "no endpoint key"
    return "enabled"


@main.group(cls=command.AliasGroup)
def telemetry():
    """See and control pseudonymous usage telemetry."""


@telemetry.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_session
@click.pass_context
def status(ctx, opts):
    """Show whether usage telemetry is on, and why."""
    reason = _reason(opts, usage_capture.typed_flags(ctx.meta))
    data = {
        "enabled": reason == "enabled",
        "reason": reason,
        "log_mode": settings.log_mode(),
        "install_id_enabled": settings.install_id_enabled(),
        "endpoint": settings.host(),
    }
    if not utils.maybe_print_as_json(opts, data):
        click.echo(f"Usage telemetry: {'on' if data['enabled'] else 'off'} ({reason})")
        click.echo(f"Log mode: {'on' if data['log_mode'] else 'off'}")
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
