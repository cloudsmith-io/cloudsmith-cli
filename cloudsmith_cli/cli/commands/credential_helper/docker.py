"""
Docker credential helper command.

Implements the Docker credential helper protocol for Cloudsmith registries.

See: https://github.com/docker/docker-credential-helpers
"""

import json
import sys

import click

from ....credential_helpers.docker import get_credentials
from ...decorators import common_api_auth_options, resolve_credentials


@click.command()
@common_api_auth_options
@resolve_credentials
def docker(opts):
    """
    Docker credential helper for Cloudsmith registries.

    Reads a Docker registry server URL from stdin and returns credentials in JSON format.
    This command implements the 'get' operation of the Docker credential helper protocol.

    Only provides credentials for Cloudsmith Docker registries (docker.cloudsmith.io).

    Input (stdin):
        Server URL as plain text (e.g., "docker.cloudsmith.io")

    Output (stdout):
        JSON: {"Username": "token", "Secret": "<cloudsmith-token>"}

    Exit codes:
        0: Success
        1: Error (no credentials available, not a Cloudsmith registry, etc.)

    Examples:
        # Manual testing
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker
        {"Username":"token","Secret":"eyJ0eXAiOiJKV1Qi..."}

        # Called by Docker via wrapper
        $ echo "docker.cloudsmith.io" | docker-credential-cloudsmith get
        {"Username":"token","Secret":"eyJ0eXAiOiJKV1Qi..."}

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG: Organization slug (required for custom domain support)
    """
    try:
        server_url = sys.stdin.read().strip()

        if not server_url:
            click.echo("Error: No server URL provided on stdin", err=True)
            sys.exit(1)

        credentials = get_credentials(
            server_url,
            credential=opts.credential,
            session=opts.session,
            api_host=opts.api_host or "https://api.cloudsmith.io",
        )

        if not credentials:
            click.echo(
                "Error: Unable to retrieve credentials. "
                "Make sure you have a valid cloudsmith-cli session, "
                "this can be checked with `cloudsmith whoami`.",
                err=True,
            )
            sys.exit(1)

        click.echo(json.dumps(credentials))

    except Exception as e:  # pylint: disable=broad-exception-caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
