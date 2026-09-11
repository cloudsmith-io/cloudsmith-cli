"""CLI/Commands - Update the CLI to the latest released version."""

import click

from ...core import installation, self_update, update_check
from ...core.session import create_requests_session
from ...core.version import get_version, parse_version
from .. import decorators, utils
from ..utils import maybe_spinner
from .main import main


def _fetch_manifest(opts, session, target):
    import requests

    try:
        with maybe_spinner(opts):
            return update_check.fetch_latest_manifest(session, target=target)
    except (requests.RequestException, ValueError) as exc:
        raise click.ClickException(f"Failed to fetch the latest version: {exc}")


def _is_up_to_date(latest, current):
    try:
        return parse_version(latest) <= parse_version(current)
    except ValueError as exc:
        raise click.ClickException(f"Cannot compare versions: {exc}")


def _confirm_self_update(opts, current, latest, assume_yes):
    """Return True to proceed with the self-update.

    Auto-confirms when ``--yes`` is given, when output is machine-readable, or
    when stderr is not a terminal (so scripted/piped invocations do not hang on
    a prompt).
    """
    if assume_yes or utils.should_use_stderr(opts) or not update_check.stderr_is_tty():
        return True
    return click.confirm(
        f"Update the Cloudsmith CLI from {current} to {latest}?", default=True
    )


def _run_self_update(opts, session, manifest, data):
    import requests

    use_stderr = utils.should_use_stderr(opts)
    click.echo(
        f"Downloading and installing version {manifest['version']} ... ",
        nl=False,
        err=use_stderr,
    )
    try:
        with maybe_spinner(opts):
            self_update.perform_self_update(manifest, session=session)
    except (self_update.SelfUpdateError, requests.RequestException, OSError) as exc:
        click.secho("ERROR", fg="red", err=use_stderr)
        raise click.ClickException(str(exc))
    click.secho("OK", fg="green", err=use_stderr)
    data["upgraded"] = True
    if utils.maybe_print_as_json(opts, data):
        return
    click.echo(f"The Cloudsmith CLI is now at version {manifest['version']}.")


def _print_manual_update(opts, current, latest, manifest, data):
    """Report a manual-update path when self-update cannot run (Windows).

    The command already holds the host manifest, so it shows the exact archive
    URL and checksum rather than a vague pointer; it exits 0 so scripts do not
    treat "update available, self-update unsupported" as a failure.
    """
    data["outcome"] = "manual"
    data["download_url"] = manifest.get("url")
    data["sha256"] = manifest.get("sha256")
    data["archive"] = manifest.get("archive")
    if utils.maybe_print_as_json(opts, data):
        return
    click.echo(
        f"A new version of the Cloudsmith CLI is available: {current} \u2192 {latest}"
    )
    click.echo("Self-update is not supported for the standalone binary on Windows.")
    click.echo(
        "Download and extract this archive, then replace your install directory:"
    )
    click.echo(f"  URL:    {manifest['url']}")
    click.echo(f"  SHA256: {manifest['sha256']}")


@main.command(aliases=["upgrade"])
@click.option(
    "-y",
    "--yes",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Do not prompt for confirmation before installing an update.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def update(ctx, opts, assume_yes):
    """Update the Cloudsmith CLI to the latest released version.

    The check runs on every invocation, independent of the once-a-day
    background version check. A standalone binary downloads and installs the
    latest release in place; every other install channel is told the correct
    upgrade command for that channel.
    """
    # pylint: disable=unused-argument
    current = get_version()
    channel = installation.detect_channel()
    target = installation.detect_target()
    if channel == installation.CHANNEL_STANDALONE and target is None:
        raise click.ClickException(
            "Cannot detect a supported platform for the standalone binary."
        )

    session = create_requests_session(user_agent=opts.api_user_agent)
    manifest = _fetch_manifest(opts, session, target)
    latest = manifest["version"]

    # Stamp both timestamps regardless of the outcome: the user has just run an
    # explicit check, so the background notice's daily re-nag is disarmed.
    update_check.record_checked_and_notified(latest)

    data = {"current_version": current, "latest_version": latest, "channel": channel}

    if _is_up_to_date(latest, current):
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
            f"A new version of the Cloudsmith CLI is available: {current} \u2192 {latest}"
        )
        click.echo(f"The CLI was installed via {channel}. To update, run:")
        click.echo(f"  {instruction}")
        return

    if not installation.self_update_supported():
        _print_manual_update(opts, current, latest, manifest, data)
        return

    if not _confirm_self_update(opts, current, latest, assume_yes):
        data["upgraded"] = False
        if not utils.maybe_print_as_json(opts, data):
            click.echo("Update cancelled.")
        return

    _run_self_update(opts, session, manifest, data)
