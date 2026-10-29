# Copyright 2026 Cloudsmith Ltd
"""
pnpm credential helper command.

Implements the pnpm credential helper protocol for Cloudsmith registries.
"""

import sys
from typing import NoReturn

import click

from ....credential_helpers.pnpm import execute
from ...config import Options
from ...decorators import common_api_auth_options, resolve_credentials
from ...usage_capture import TrackedCommand


@click.command(cls=TrackedCommand)
@click.argument("repo", required=False, default="npm.cloudsmith.io")
@common_api_auth_options
@resolve_credentials
def pnpm(opts: Options, repo: str) -> NoReturn:
    """
    pnpm credential helper for Cloudsmith registries.

    Prints the authorization value for a pnpm registry.  pnpm runs this
    command through the ``tokenHelper`` setting in the user-level ``~/.npmrc``
    file.  Use ``cloudsmith credential-helper install pnpm`` to add that
    setting.

    Provides credentials for all Cloudsmith npm registries: ``*.cloudsmith.io``,
    ``*.cloudsmith.com``, and any custom domains configured for the Workspace
    (requires a Workspace - ``--workspace``, CLOUDSMITH_WORKSPACE, or
    ``workspace`` in ``config.ini``; legacy aliases are also accepted - and a
    valid API key/token).

    \b
    Input (argument, optional):
        Registry host (default: "npm.cloudsmith.io")

    \b
    Output (stdout):
        Text: token <cloudsmith-api-key>, or Bearer <cloudsmith-token>

    \b
    Exit codes:
        0: Success
        1: Error (no credentials available, not a Cloudsmith registry, etc.)

    \b
    Examples:
        # Manual testing
        $ cloudsmith credential-helper pnpm npm.cloudsmith.io

    \b
        # Called by pnpm via the launcher
        $ pnpm-credential-cloudsmith

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_WORKSPACE: Workspace slug (CLOUDSMITH_ORG is also accepted)
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
