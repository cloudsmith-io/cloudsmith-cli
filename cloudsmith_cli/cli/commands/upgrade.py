"""CLI/Commands - Upgrade the CLI."""

import click
import requests

from ...core import installation, self_update, update_check
from ...core.version import get_version, parse_version
from .. import decorators, utils
from ..utils import maybe_spinner
from .main import main


def _fetch_manifest(opts, target):
    try:
        with maybe_spinner(opts):
            return update_check.fetch_latest_manifest(target=target)
    except (requests.RequestException, ValueError) as exc:
        raise click.ClickException(f"Failed to fetch the latest version: {exc}")


def _is_up_to_date(latest, current):
    try:
        return parse_version(latest) <= parse_version(current)
    except ValueError as exc:
        raise click.ClickException(f"Cannot compare versions: {exc}")


def _run_self_update(opts, manifest, data):
    use_stderr = utils.should_use_stderr(opts)
    click.echo(
        f"Downloading and installing version {manifest['version']} ... ",
        nl=False,
        err=use_stderr,
    )
    try:
        with maybe_spinner(opts):
            self_update.perform_self_update(manifest)
    except (self_update.SelfUpdateError, requests.RequestException, OSError) as exc:
        click.secho("ERROR", fg="red", err=use_stderr)
        raise click.ClickException(str(exc))
    click.secho("OK", fg="green", err=use_stderr)
    data["upgraded"] = True
    if utils.maybe_print_as_json(opts, data):
        return
    click.echo(f"The Cloudsmith CLI is now at version {manifest['version']}.")


@main.command(aliases=["update"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def upgrade(ctx, opts):
    """Upgrade the Cloudsmith CLI to the latest released version.

    The command detects how the CLI was installed. A standalone binary
    replaces itself with the latest release. Every other install channel
    gets the correct upgrade command for that channel.
    """
    current = get_version()
    channel = installation.detect_channel()
    target = installation.detect_target()
    if channel == installation.CHANNEL_STANDALONE and target is None:
        raise click.ClickException(
            "Cannot detect a supported platform for the standalone binary."
        )

    manifest = _fetch_manifest(opts, target)
    latest = manifest["version"]
    up_to_date = _is_up_to_date(latest, current)
    update_check.store_latest_version(latest)

    data = {"current_version": current, "latest_version": latest, "channel": channel}

    if up_to_date:
        data["up_to_date"] = True
        if not utils.maybe_print_as_json(opts, data):
            click.echo(f"The Cloudsmith CLI is up to date (version {current}).")
        return

    instruction = installation.upgrade_instruction(channel)
    if instruction is not None:
        data["upgrade_command"] = instruction
        if utils.maybe_print_as_json(opts, data):
            return
        click.echo(
            f"A new version of the Cloudsmith CLI is available: {current} → {latest}"
        )
        click.echo(f"The CLI was installed via {channel}. To upgrade, run:")
        click.echo(f"  {instruction}")
        return

    _run_self_update(opts, manifest, data)
