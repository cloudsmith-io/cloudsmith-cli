"""
npm/pnpm token helper command.

Prints a raw Cloudsmith API token for use with pnpm's tokenHelper.

See: https://pnpm.io/npmrc#url-tokenhelper
"""

import sys

import click

from ....credential_helpers.npm import get_token


@click.command()
def npm():
    """
    npm/pnpm token helper for Cloudsmith registries.

    Prints a raw API token to stdout for use with pnpm's tokenHelper configuration.

    Examples:
        # Direct usage
        $ cloudsmith credential-helper npm
        eyJ0eXAiOiJKV1Qi...

        # Via wrapper (called by pnpm)
        $ npm-credentials-cloudsmith
        eyJ0eXAiOiJKV1Qi...

    Configuration in ~/.npmrc:
        //npm.cloudsmith.io/:tokenHelper=/absolute/path/to/npm-credentials-cloudsmith

    Find the path with: which npm-credentials-cloudsmith

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG: Organization slug (required for OIDC)
        CLOUDSMITH_SERVICE_SLUG: Service account slug (required for OIDC)
    """
    try:
        token = get_token(debug=False)

        if not token:
            click.echo(
                "Error: Unable to retrieve credentials. "
                "Set CLOUDSMITH_API_KEY or configure OIDC.",
                err=True,
            )
            sys.exit(1)

        sys.stdout.write(token)
        sys.stdout.flush()

    except Exception as e:  # pylint: disable=broad-exception-caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
