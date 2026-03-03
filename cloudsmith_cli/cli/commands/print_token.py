"""CLI/Commands - Print the active authentication token."""

import click

from .. import decorators, utils
from .main import main


def _extract_token(api_config):
    """Extract the active token from the API configuration.

    Returns (token, token_type) where token_type is 'bearer' or 'api_key'.
    """
    headers = getattr(api_config, "headers", {}) or {}
    auth_header = headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :], "bearer"

    api_keys = getattr(api_config, "api_key", {}) or {}
    api_key = api_keys.get("X-Api-Key")
    if api_key:
        return api_key, "api_key"

    return None, None


@main.command(name="print-token")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def token(ctx, opts):
    """Print the active authentication token.

    Outputs the token currently used to authenticate with the Cloudsmith API.
    This is useful for passing to other tools like curl, docker, pip, etc.

    Note: This prints your CURRENT/ACTIVE token. To LOGIN and get a NEW token
    interactively, use 'cloudsmith login' (or its alias 'cloudsmith token').

    ⚠️  WARNING: This command prints sensitive credentials to stdout.
    Avoid running this command in logged/recorded terminal sessions.
    The token will appear in your shell history if stored in a variable.

    For safer usage, pipe directly to another command without storing
    in variables.

    \b
    Examples:
      # Use with curl (pipe directly)
      cloudsmith print-token | xargs -I{} curl -H "X-Api-Key: {}" https://api.cloudsmith.io/v1/user/self/

      # Use with docker login (pipe to stdin)
      cloudsmith print-token | docker login docker.cloudsmith.io -u token --password-stdin

      # Avoid: storing in shell variable (appears in history)
      # export CS_TOKEN=$(cloudsmith print-token)  # NOT RECOMMENDED

    \b
    See also:
      cloudsmith login     Interactive login to get a NEW token
      cloudsmith whoami    Show current authentication status
    """
    active_token, token_type = _extract_token(opts.api_config)

    if not active_token:
        click.secho("Error: No authentication token available", fg="red", err=True)
        click.echo(err=True)
        click.echo("Try one of these commands to authenticate:", err=True)
        click.echo(
            "  "
            + click.style("cloudsmith login", fg="cyan")
            + "              # Interactive login",
            err=True,
        )
        click.echo(
            "  "
            + click.style("cloudsmith authenticate", fg="cyan")
            + "       # SAML/SSO login",
            err=True,
        )
        click.echo(
            "  "
            + click.style("export CLOUDSMITH_API_KEY=...", fg="cyan")
            + " # Set via environment variable",
            err=True,
        )
        click.echo(err=True)
        click.echo(
            "For OIDC auto-discovery, set CLOUDSMITH_ORG and CLOUDSMITH_SERVICE_SLUG",
            err=True,
        )
        ctx.exit(1)

    if utils.maybe_print_as_json(
        opts,
        {"token": active_token, "type": token_type},
    ):
        return

    # Print bare token to stdout (stderr used for any messages)
    click.echo(active_token)
