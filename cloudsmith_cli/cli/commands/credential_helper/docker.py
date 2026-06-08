"""
Docker credential helper command.

Implements the Docker credential helper protocol for Cloudsmith registries.

See: https://github.com/docker/docker-credential-helpers
"""

import sys

import click

from ....credential_helpers.docker import execute
from ...decorators import common_api_auth_options, resolve_credentials


@click.command()
@click.argument("operation", required=False, default="get")
@common_api_auth_options
@resolve_credentials
def docker(opts, operation):
    """
    Docker credential helper for Cloudsmith registries.

    Reads a Docker registry server URL from stdin and returns credentials in
    JSON format.  Implements the full Docker credential helper protocol
    (get/store/erase/list).

    Provides credentials for all Cloudsmith Docker registries: ``*.cloudsmith.io``,
    ``*.cloudsmith.com``, and any custom domains configured for the organisation
    (requires CLOUDSMITH_ORG and a valid API key/token).

    Input (stdin):
        Server URL as plain text (e.g. "docker.cloudsmith.io")

    Output (stdout):
        JSON: {"Username": "token", "Secret": "<cloudsmith-token>"}

    Exit codes:
        0: Success
        1: Error (no credentials available, not a Cloudsmith registry, etc.)

    Examples:
        # Manual testing
        $ echo "docker.cloudsmith.io" | cloudsmith credential-helper docker

        # Called by Docker via launcher
        $ echo "docker.cloudsmith.io" | docker-credential-cloudsmith get

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG:     Organisation slug (required for custom domain support)
    """
    exit_code, stdout, stderr = execute(
        operation,
        sys.stdin,
        credential=opts.credential,
        api_host=opts.api_host,
    )

    if stdout is not None:
        click.echo(stdout)
    if stderr is not None:
        click.echo(stderr, err=True)
    sys.exit(exit_code)
