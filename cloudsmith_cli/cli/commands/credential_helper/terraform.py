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


@click.command(context_settings={"ignore_unknown_options": True})
@click.argument("params", nargs=-1, type=click.UNPROCESSED)
@common_cli_config_options
@common_api_auth_options
@resolve_credentials
def terraform(opts, params):
    """
    Terraform credentials helper for Cloudsmith registries.

    Resolves the token for a Cloudsmith Terraform registry and prints it in
    Terraform's expected JSON credentials format: ``{"token": "..."}``.

    Provides credentials for all Cloudsmith Terraform registries:
    ``*.cloudsmith.io``, ``*.cloudsmith.com``, and any custom domains
    configured for the organisation (requires an organisation - ``--org``,
    CLOUDSMITH_ORG or ``org`` in ``config.ini`` - and a valid API key/token).

    Accepts Terraform's calling convention — an optional verb (``get``,
    ``store``, ``forget``) followed by the hostname — so the on-PATH launcher
    can forward Terraform's arguments verbatim.  When no verb is given the
    action is ``get``.  When no hostname is given it is read from stdin.  Only
    ``get`` is served; ``store``/``forget`` return an error and a non-zero exit.

    A hostname that is not a Cloudsmith registry yields an empty object
    (``{}``) and exit 0 so Terraform falls back to its own credential sources.

    \b
    Input (arguments or stdin):
        [VERB] HOSTNAME — e.g. "get terraform.cloudsmith.io" or just
        "terraform.cloudsmith.io"; HOSTNAME alone may also come from stdin.

    \b
    Output (stdout):
        JSON: {"token": "<cloudsmith-token>"}  (Cloudsmith host, token found)
        JSON: {}                               (not a Cloudsmith host)

    \b
    Exit codes:
        0: Token returned, or the host is not a Cloudsmith registry
        1: Cloudsmith host with no credentials available, or an error occurred

    The organisation and profile can be supplied with ``--org`` and
    ``-P/--profile`` instead of environment variables.  The launcher forwards
    Terraform's ``args`` verbatim, so a terraformrc block such as
    ``credentials_helper "cloudsmith" { args = ["--org=acme", "-P", "ci"] }``
    reaches this command as those options.

    \b
    Examples:
        # Direct usage
        $ cloudsmith credential-helper terraform terraform.cloudsmith.io
        {"token": "..."}

        # Terraform's calling convention (verb + hostname)
        $ cloudsmith credential-helper terraform get terraform.cloudsmith.io

        # Select an org and profile explicitly (no env vars needed)
        $ cloudsmith credential-helper terraform --org=acme -P ci get terraform.cloudsmith.io

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG:     Organisation slug (required for custom domain support)
        CLOUDSMITH_PROFILE: Configuration profile to load (optional)
    """
    # Terraform passes "<verb> <hostname>"; direct/manual use may pass just the
    # hostname (verb defaults to "get") or nothing (hostname read from stdin).
    verb = "get"
    hostname: str | None = None
    if len(params) >= 2:
        verb, hostname = params[-2], params[-1]
    elif len(params) == 1:
        hostname = params[0]

    if not hostname:
        try:
            hostname = sys.stdin.read().strip()
        except (OSError, ValueError):
            hostname = ""

    exit_code, stdout, stderr = execute(
        verb,
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
