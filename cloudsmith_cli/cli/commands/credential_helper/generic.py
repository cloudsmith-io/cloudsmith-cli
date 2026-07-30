# Copyright 2026 Cloudsmith Ltd
"""
Generic credential helper command.

Emits a versioned JSON credential document.
"""

import sys

import click

from ....credential_helpers.generic import execute
from ...decorators import common_api_auth_options, resolve_credentials


@click.command()
@common_api_auth_options
@resolve_credentials
def generic(opts):
    """
    Emit a Cloudsmith credential as JSON.

    Resolves a credential through the full provider chain and writes a
    versioned JSON document to stdout.  Takes no arguments: a Cloudsmith token
    is organisation-wide, so the host it will be used against does not change
    which credential resolves.

    Output (stdout):
        JSON: {"version": 1, "username": "token", "password": "<token>"}

    Exit codes:
        0: Success
        1: No credential could be resolved

    Examples:
        # Resolve a credential
        $ cloudsmith credential-helper generic

        # Extract just the token
        $ cloudsmith credential-helper generic | jq -r .password

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
    """
    exit_code, stdout, stderr = execute(credential=opts.credential)

    if stdout is not None:
        click.echo(stdout)
    if stderr is not None:
        click.echo(stderr, err=True)
    sys.exit(exit_code)
