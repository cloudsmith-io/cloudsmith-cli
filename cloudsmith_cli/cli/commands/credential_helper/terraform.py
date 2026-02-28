"""
Terraform credential helper command.

Implements the Terraform credential helper protocol for Cloudsmith registries.

See: https://developer.hashicorp.com/terraform/internals/credentials-helpers
"""

import json
import sys

import click

from ....credential_helpers.terraform import get_credentials


@click.command()
@click.argument("hostname", required=False, default=None)
def terraform(hostname):
    """
    Terraform credential helper for Cloudsmith registries.

    Returns credentials in Terraform's expected JSON format: {"token": "..."}

    Can be used directly or via the terraform-credentials-cloudsmith wrapper.

    If HOSTNAME is provided as an argument, uses it directly.
    Otherwise reads from stdin (for use with the wrapper binary).

    Examples:
        # Direct usage
        $ cloudsmith credential-helper terraform terraform.cloudsmith.io
        {"token":"eyJ0eXAiOiJKV1Qi..."}

        # Via wrapper
        $ terraform-credentials-cloudsmith get terraform.cloudsmith.io

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG: Organization slug (required for OIDC)
        CLOUDSMITH_SERVICE_SLUG: Service account slug (required for OIDC)
    """
    try:
        if not hostname:
            hostname = sys.stdin.read().strip()

        if not hostname:
            click.echo("Error: No hostname provided", err=True)
            sys.exit(1)

        token = get_credentials(hostname, debug=False)

        if not token:
            click.echo("{}")
            sys.exit(0)

        click.echo(json.dumps({"token": token}))

    except Exception as e:  # pylint: disable=broad-exception-caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
