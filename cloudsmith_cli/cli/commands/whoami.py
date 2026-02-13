"""CLI/Commands - Retrieve authentication status."""

import os

import click

from ...core import keyring
from ...core.api.exceptions import ApiException
from ...core.api.user import get_token_metadata, get_user_brief
from .. import decorators, utils
from ..config import CredentialsReader
from ..exceptions import handle_api_exceptions
from .main import main


def _get_active_method(api_config):
    """Inspect API config to determine SSO, API key, or no auth."""
    headers = getattr(api_config, "headers", {}) or {}
    if headers.get("Authorization", "").startswith("Bearer "):
        return "sso_token"
    if (getattr(api_config, "api_key", {}) or {}).get("X-Api-Key"):
        return "api_key"
    return "none"


def _get_api_key_source(opts):
    """Determine where the API key was loaded from.

    Checks in priority order matching actual resolution:
    CLI --api-key flag > CLOUDSMITH_API_KEY env var > credentials.ini.
    """
    if not opts.api_key:
        return {"configured": False, "source": None, "source_key": None}

    env_key = os.environ.get("CLOUDSMITH_API_KEY")

    # If env var is set but differs from the resolved key, CLI flag won
    if env_key and opts.api_key != env_key:
        source, key = "CLI --api-key flag", "cli_flag"
    elif env_key:
        suffix = env_key[-4:]
        source, key = f"CLOUDSMITH_API_KEY env var (ends with ...{suffix})", "env_var"
    elif creds := CredentialsReader.find_existing_files():
        source, key = f"credentials.ini ({creds[0]})", "credentials_file"
    else:
        source, key = "CLI --api-key flag", "cli_flag"

    return {"configured": True, "source": source, "source_key": key}


def _get_sso_status(api_host):
    """Return SSO token status from the system keyring."""
    enabled = keyring.should_use_keyring()
    has_tokens = enabled and keyring.has_sso_tokens(api_host)
    refreshed = keyring.get_refresh_attempted_at(api_host) if has_tokens else None

    return {
        "configured": has_tokens,
        "keyring_enabled": enabled,
        "source": "System Keyring" if has_tokens else None,
        "last_refreshed": utils.fmt_datetime(refreshed) if refreshed else None,
    }


def _get_verbose_auth_data(opts, api_host):
    """Gather all auth details for verbose output."""
    api_key_info = _get_api_key_source(opts)
    sso_info = _get_sso_status(api_host)

    # Fetch token metadata (extra API call, graceful fallback)
    token_meta = None
    if api_key_info["configured"]:
        try:
            token_meta = get_token_metadata()
        except ApiException:
            pass

    created = token_meta.get("created") if token_meta else None
    api_key_info["slug"] = token_meta["slug"] if token_meta else None
    api_key_info["created"] = utils.fmt_datetime(created) if created else None

    return {
        "active_method": _get_active_method(opts.api_config),
        "api_key": api_key_info,
        "sso": sso_info,
    }


def _print_user_line(name, username, email):
    """Print a styled user identity line."""
    styled_name = click.style(name or "Unknown", fg="cyan")
    styled_slug = click.style(username or "Unknown", fg="magenta")
    email_part = f", email: {click.style(email, fg='green')}" if email else ""
    click.echo(f"User: {styled_name} (slug: {styled_slug}{email_part})")


def _print_verbose_text(data):
    """Print verbose authentication details as styled text."""
    click.echo()
    _print_user_line(data["name"], data["username"], data.get("email"))

    auth = data["auth"]
    active = auth["active_method"]
    ak = auth["api_key"]
    sso = auth["sso"]

    click.echo()
    if active == "sso_token":
        click.secho("Authentication Method: SSO Token (primary)", fg="cyan", bold=True)
        if sso.get("source"):
            click.echo(f"  Source: {sso['source']}")
        if sso.get("last_refreshed"):
            click.echo(
                f"  Last Refreshed: {sso['last_refreshed']} (refreshes every 30 min)"
            )
        if ak["configured"]:
            click.echo()
            click.secho("API Key: Also configured", fg="yellow")
            if ak.get("source"):
                click.echo(f"  Source: {ak['source']}")
            click.echo("  Note: SSO token is being used instead")
    elif active == "api_key":
        click.secho("Authentication Method: API Key", fg="cyan", bold=True)
        for label, field in [
            ("Source", "source"),
            ("Token Slug", "slug"),
            ("Created", "created"),
        ]:
            if ak.get(field):
                click.echo(f"  {label}: {ak[field]}")
    else:
        click.secho("Authentication Method: None (anonymous)", fg="yellow", bold=True)

    if active != "sso_token":
        click.echo()
        if not sso["keyring_enabled"]:
            click.secho(
                "SSO Status: Keyring disabled (CLOUDSMITH_NO_KEYRING)", fg="yellow"
            )
        elif sso["configured"]:
            click.secho("SSO Status: Configured (not active)", fg="yellow")
            click.echo(f"  Source: {sso['source']}")
        else:
            click.echo("SSO Status: Not configured")
            click.echo("  Keyring: Enabled (no tokens stored)")


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def whoami(ctx, opts):
    """Retrieve your current authentication status."""
    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Retrieving your authentication status from the API ... ",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to retrieve your authentication status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with utils.maybe_spinner(opts):
            is_auth, username, email, name = get_user_brief()
    click.secho("OK", fg="green", err=use_stderr)

    data = {
        "is_authenticated": is_auth,
        "username": username,
        "email": email,
        "name": name,
    }

    if opts.verbose:
        api_host = getattr(opts.api_config, "host", None) or opts.api_host
        data["auth"] = _get_verbose_auth_data(opts, api_host)

    if utils.maybe_print_as_json(opts, data):
        return

    if not is_auth:
        click.echo("You are authenticated as:")
        click.secho("Nobody (i.e. anonymous user)", fg="yellow")
        return

    if opts.verbose:
        _print_verbose_text(data)
    else:
        click.echo("You are authenticated as:")
        _print_user_line(name, username, email)
