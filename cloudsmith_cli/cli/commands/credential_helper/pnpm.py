# Copyright 2026 Cloudsmith Ltd
"""
pnpm credential helper command.

Implements the pnpm credential helper protocol for Cloudsmith registries.
"""

import sys

import click

from ....credential_helpers.pnpm import execute
from ...decorators import common_api_auth_options, resolve_credentials


@click.command()
@click.argument("repo", required=False, default="npm.cloudsmith.io")
@common_api_auth_options
@resolve_credentials
def pnpm(opts, repo):
    """
    Input (arg, optional):
        Server URL as plain text (e.g. "npm.cloudsmith.io")

    Output (stdout):
        Text: <cloudsmith-token>

    \b
    Exit codes:
        0: Success
        1: Error (no credentials available, not a Cloudsmith registry, etc.)

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG:     Organisation slug (required for custom domain support)
    """

    exit_code, stdout, stderr = execute(
        repo,
        credential=opts.credential,
        api_host=opts.api_host,
        org=opts.org,
    )

    if stdout is not None:
        click.echo(stdout, nl=False)
    if stderr is not None:
        click.echo(stderr, err=True)

    sys.exit(exit_code)
