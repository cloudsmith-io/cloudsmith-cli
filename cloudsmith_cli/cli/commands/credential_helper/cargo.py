# Copyright 2026 Cloudsmith Ltd
"""
Cargo credential provider command.

Implements the Cargo credential provider protocol for Cloudsmith registries.

See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html
"""

import sys

import click

from ....credential_helpers.cargo import execute
from ...decorators import common_api_auth_options, resolve_credentials


@click.command(context_settings={"ignore_unknown_options": True})
@click.option(
    "--cargo-plugin",
    is_flag=True,
    default=False,
    hidden=True,
    help="Passed by Cargo when invoking this command as a credential provider.",
)
@click.argument("provider_args", nargs=-1, type=click.UNPROCESSED)
@common_api_auth_options
@resolve_credentials
def cargo(opts, cargo_plugin, provider_args):  # pylint: disable=unused-argument
    """
    Cargo credential provider for Cloudsmith registries.

    Speaks the Cargo credential provider protocol: a newline-delimited JSON
    conversation on stdin/stdout, starting with a hello message that announces
    the supported protocol versions, then one response per request.

    Provides credentials for all Cloudsmith Cargo registries: ``*.cloudsmith.io``,
    ``*.cloudsmith.com``, and any custom domains configured for the Workspace
    (requires a Workspace - ``--workspace``, CLOUDSMITH_WORKSPACE, or
    ``workspace`` in ``config.ini``; legacy aliases are also accepted - and a
    valid API key/token).

    A registry that is not a Cloudsmith one is answered with
    ``url-not-supported`` so Cargo falls through to the next configured
    credential provider.  ``cargo login``/``cargo logout`` are answered with
    ``operation-not-supported``: credentials come from the Cloudsmith CLI's own
    provider chain, so there is nothing to store or clear.

    \b
    Input (stdin):
        One JSON request per line, e.g.
        {"v":1,"kind":"get","operation":"read",
         "registry":{"index-url":"sparse+https://cargo.cloudsmith.io/org/repo/"}}

    \b
    Output (stdout):
        {"v":[1]}
        {"Ok":{"kind":"get","token":"<cloudsmith-token>","cache":"session",
               "operation_independent":true}}

    \b
    Exit codes:
        0: Session completed
        1: No credentials available, or the session broke down

    \b
    Examples:
        # Manual testing
        $ echo '{"v":1,"kind":"get","operation":"read","registry":{"index-url":"sparse+https://cargo.cloudsmith.io/org/repo/"}}' \\
            | cloudsmith credential-helper cargo

        # Called by Cargo via the launcher
        $ cargo-credential-cloudsmith --cargo-plugin

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_WORKSPACE: Workspace slug (CLOUDSMITH_ORG is also accepted)
    """
    # `provider_args` collects the extra arguments Cargo appends from the
    # credential-provider config entry.  This provider takes no configuration
    # of its own, so they are accepted and ignored rather than rejected — an
    # unknown-option error would surface as an authentication failure.
    exit_code, stderr = execute(
        sys.stdin,
        sys.stdout,
        credential=opts.credential,
        api_host=opts.api_host,
        org=opts.org,
    )

    if stderr is not None:
        click.echo(stderr, err=True)
    sys.exit(exit_code)
