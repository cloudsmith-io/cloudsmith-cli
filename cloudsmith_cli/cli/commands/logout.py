# Copyright 2026 Cloudsmith Ltd
"""CLI/Commands - Log out and clear authentication state."""

import os

import click
import cloudsmith_api

from ...core import keyring
from .. import decorators, utils
from ..config import CredentialsReader
from .main import main


def _clear_credentials(dry_run, use_stderr):
    """Clear credential files. Returns result dict."""
    creds_files = CredentialsReader.find_existing_files()
    if not creds_files:
        click.echo("No credentials file found.", err=use_stderr)
        return {"action": "not_found", "files": []}

    if not dry_run:
        for path in creds_files:
            CredentialsReader.clear_api_key(path)

    verb = "Would remove" if dry_run else "Removed"
    for path in creds_files:
        click.echo(
            f"{verb} credentials from: " + click.style(path, bold=True),
            err=use_stderr,
        )
    action = "would_remove" if dry_run else "removed"
    return {"action": action, "files": list(creds_files)}


def _clear_keyring(api_host, dry_run, use_stderr):
    """Clear SSO tokens from keyring. Returns result dict."""
    if not keyring.should_use_keyring():
        click.secho(
            "Keyring is disabled (CLOUDSMITH_NO_KEYRING is set).",
            fg="yellow",
            err=use_stderr,
        )
        return {"action": "disabled"}

    if not keyring.has_sso_tokens(api_host):
        click.echo("No SSO tokens found in system keyring.", err=use_stderr)
        return {"action": "not_found"}

    if dry_run:
        click.echo("Would remove SSO tokens from system keyring.", err=use_stderr)
        return {"action": "would_remove"}

    keyring.delete_sso_tokens(api_host)
    click.echo("Removed SSO tokens from system keyring.", err=use_stderr)
    return {"action": "removed"}


def _env_api_key_status():
    """Return structured status for the CLOUDSMITH_API_KEY env var."""
    is_set = bool(os.environ.get("CLOUDSMITH_API_KEY"))
    return {
        "is_set": is_set,
        "action": "unset CLOUDSMITH_API_KEY" if is_set else "none",
    }


def _collect_warnings(keyring_only, config_only):
    """Collect advisory warnings based on flags and environment."""
    warnings = []
    if config_only:
        warnings.append("SSO tokens were not modified (--config-only).")
    if keyring_only:
        warnings.append("credentials.ini was not modified (--keyring-only).")
    if os.environ.get("CLOUDSMITH_API_KEY"):
        warnings.append(
            "CLOUDSMITH_API_KEY is set in your environment. "
            "Run: unset CLOUDSMITH_API_KEY"
        )
    return warnings


@main.command()
@click.option(
    "--api-host",
    envvar="CLOUDSMITH_API_HOST",
    default=None,
    help="The API host to clear keyring tokens for.",
)
@click.option(
    "--keyring-only",
    is_flag=True,
    default=False,
    help="Only clear SSO tokens from the system keyring.",
)
@click.option(
    "--config-only",
    is_flag=True,
    default=False,
    help="Only clear credentials from credentials.ini.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be removed without removing anything.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def logout(ctx, opts, api_host, keyring_only, config_only, dry_run):
    """Clear stored authentication credentials and SSO tokens."""
    if keyring_only and config_only:
        raise click.UsageError(
            "--keyring-only and --config-only are mutually exclusive."
        )

    if api_host is None:
        api_host = cloudsmith_api.Configuration().host

    use_stderr = utils.should_use_stderr(opts)

    credential_file = (
        _clear_credentials(dry_run, use_stderr)
        if not keyring_only
        else {"action": "skipped", "files": []}
    )
    keyring_result = (
        _clear_keyring(api_host, dry_run, use_stderr)
        if not config_only
        else {"action": "skipped"}
    )
    warnings = _collect_warnings(keyring_only, config_only)

    for warning in warnings:
        click.secho(f"Note: {warning}", fg="yellow", err=use_stderr)

    utils.maybe_print_as_json(
        opts,
        {
            "api_host": api_host,
            "dry_run": dry_run,
            "sources": {
                "credential_file": credential_file,
                "keyring": keyring_result,
                "environment_api_key": _env_api_key_status(),
            },
        },
    )
