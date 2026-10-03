# Copyright 2026 Cloudsmith Ltd
"""
NuGet credential provider command.

Implements the NuGet cross-platform authentication plugin protocol and the
nuget.exe credential provider protocol for Cloudsmith feeds.

See:
    https://learn.microsoft.com/en-us/nuget/reference/extensibility/nuget-cross-platform-plugins
    https://learn.microsoft.com/en-us/nuget/reference/extensibility/nuget-exe-credential-providers
"""

import sys

import click

from ....credential_helpers.nuget import execute
from ...decorators import common_api_auth_options, resolve_credentials


def _utf8(stream, **kwargs):
    """Switch a text stream to UTF-8, which both NuGet protocols require."""
    try:
        stream.reconfigure(encoding="utf-8", **kwargs)
    except (AttributeError, ValueError, OSError):
        pass
    return stream


@click.command(
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False}
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Treat this hostname as a Cloudsmith NuGet feed (repeatable), in "
    "addition to Cloudsmith domains and the Workspace's NuGet custom domains.",
)
@click.argument("nuget_args", nargs=-1, type=click.UNPROCESSED)
@common_api_auth_options
@resolve_credentials
def nuget(opts, domains, nuget_args):
    """
    NuGet credential provider for Cloudsmith feeds.

    NuGet runs this command through the ``nuget-plugin-cloudsmith`` launcher
    that ``cloudsmith credential-helper install nuget`` puts on PATH.  NuGet's
    own arguments follow ``--``:

    \b
      -Plugin       Speak the cross-platform plugin protocol (dotnet, MSBuild,
                    NuGet.exe, Visual Studio) on stdin/stdout.
      -Uri URI      Answer one nuget.exe (v1) credential request with JSON.

    Provides credentials for all Cloudsmith NuGet feeds: ``*.cloudsmith.io``,
    ``*.cloudsmith.com``, and any NuGet custom domains configured for the
    Workspace (requires a Workspace - ``--workspace``, CLOUDSMITH_WORKSPACE,
    or ``workspace`` in ``config.ini``; legacy aliases are also accepted - and
    a valid API key/token).  Any other feed is declined so NuGet falls back to
    its other credential sources.

    \b
    Output (stdout, -Uri):
        JSON: {"Username": "token", "Password": "<cloudsmith-token>", "Message": ""}

    \b
    Exit codes (-Uri):
        0: Success
        1: Not a Cloudsmith feed (NuGet tries the next provider)
        2: A Cloudsmith feed, but no credentials are available

    \b
    Examples:

    \b
        # Manual testing
        $ cloudsmith credential-helper nuget -- \\
            -Uri https://nuget.cloudsmith.io/WORKSPACE/REPO/v3/index.json
    \b
        # Called by NuGet via the launcher
        $ nuget-plugin-cloudsmith -Plugin

    \b
    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_WORKSPACE: Workspace slug (CLOUDSMITH_ORG is also accepted)
    """
    exit_code, stderr = execute(
        nuget_args,
        _utf8(sys.stdin),
        _utf8(sys.stdout, newline="\n"),
        credential=opts.credential,
        api_host=opts.api_host,
        org=opts.org,
        extra_domains=domains,
    )

    if stderr is not None:
        click.echo(stderr, err=True)
    sys.exit(exit_code)
