"""
NuGet credential helper command.

Implements credential retrieval for NuGet feeds hosted on Cloudsmith.

See: https://learn.microsoft.com/en-us/nuget/reference/extensibility/nuget-exe-credential-providers
"""

import json
import sys

import click

from ....credential_helpers.nuget import get_credentials


@click.command()
@click.argument("uri", required=False, default=None)
def nuget(uri):
    """
    NuGet credential helper for Cloudsmith feeds.

    Returns credentials in NuGet's expected JSON format:
    {"Username": "token", "Password": "...", "Message": ""}

    If URI is provided as an argument, uses it directly.
    Otherwise reads from stdin.

    Examples:
        # Direct usage
        $ cloudsmith credential-helper nuget https://nuget.cloudsmith.io/org/repo/v3/index.json
        {"Username":"token","Password":"eyJ0eXAiOiJKV1Qi...","Message":""}

        # Via wrapper (called by NuGet)
        $ CredentialProvider.Cloudsmith -uri https://nuget.cloudsmith.io/org/repo/v3/index.json

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG: Organization slug (required for OIDC)
        CLOUDSMITH_SERVICE_SLUG: Service account slug (required for OIDC)
    """
    try:
        if not uri:
            uri = sys.stdin.read().strip()

        if not uri:
            click.echo("Error: No URI provided", err=True)
            sys.exit(1)

        credentials = get_credentials(uri, debug=False)

        if not credentials:
            click.echo(
                "Error: Unable to retrieve credentials. "
                "Set CLOUDSMITH_API_KEY or configure OIDC.",
                err=True,
            )
            sys.exit(1)

        click.echo(json.dumps({**credentials, "Message": ""}))

    except Exception as e:  # pylint: disable=broad-exception-caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
