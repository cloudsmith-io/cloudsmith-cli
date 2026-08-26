# Copyright 2026 Cloudsmith Ltd
"""
Terraform credentials helper command.

Implements the ``get`` verb of Terraform's credentials-helper protocol for
Cloudsmith registries.  The ``terraform-credentials-cloudsmith`` wrapper binary
delegates here.

See: https://developer.hashicorp.com/terraform/internals/credentials-helpers
"""

import sys

import click

from ....credential_helpers.terraform import execute
from ...decorators import (
    common_api_auth_options,
    common_cli_config_options,
    resolve_credentials,
)


@click.command()
@click.argument("hostname", required=False, default=None)
@common_cli_config_options
@common_api_auth_options
@resolve_credentials
def terraform(opts, hostname):
    """
    Terraform credentials helper for Cloudsmith registries.

    Resolves the token for a Cloudsmith Terraform registry and prints it in
    Terraform's expected JSON credentials format: ``{"token": "..."}``.

    Provides credentials for all Cloudsmith Terraform registries:
    ``*.cloudsmith.io``, ``*.cloudsmith.com``, and any custom domains
    configured for the organisation (requires an organisation - ``--org``,
    CLOUDSMITH_ORG or ``org`` in ``config.ini`` - and a valid API key/token).

    The hostname may be given as an argument; otherwise it is read from stdin.
    A hostname that is not a Cloudsmith registry yields an empty object
    (``{}``) and exit 0 so Terraform falls back to its own credential sources.

    \b
    Input (argument or stdin):
        Registry hostname as plain text (e.g. "terraform.cloudsmith.io")

    \b
    Output (stdout):
        JSON: {"token": "<cloudsmith-token>"}  (Cloudsmith host, token found)
        JSON: {}                               (not a Cloudsmith host)

    \b
    Exit codes:
        0: Token returned, or the host is not a Cloudsmith registry
        1: Cloudsmith host with no credentials available, or an error occurred

    The organisation and profile can be supplied with ``--org`` and
    ``-P/--profile`` instead of environment variables.  The wrapper binary
    forwards Terraform's ``args`` verbatim, so a terraformrc block such as
    ``credentials_helper "cloudsmith" { args = ["--org=acme", "-P", "ci"] }``
    reaches this command as those options.

    \b
    Examples:
        # Direct usage
        $ cloudsmith credential-helper terraform terraform.cloudsmith.io
        {"token": "..."}

        # Select an org and profile explicitly (no env vars needed)
        $ cloudsmith credential-helper terraform --org=acme -P ci terraform.cloudsmith.io

        # Via the wrapper binary Terraform invokes
        $ terraform-credentials-cloudsmith get terraform.cloudsmith.io

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG:     Organisation slug (required for custom domain support)
        CLOUDSMITH_PROFILE: Configuration profile to load (optional)
    """
    if not hostname:
        try:
            hostname = sys.stdin.read().strip()
        except (OSError, ValueError):
            hostname = ""

    exit_code, stdout, stderr = execute(
        "get",
        hostname,
        credential=opts.credential,
        api_host=opts.api_host,
        org=opts.org,
    )

    if stdout is not None:
        click.echo(stdout)
    if stderr is not None:
        click.echo(stderr, err=True)
    sys.exit(exit_code)
