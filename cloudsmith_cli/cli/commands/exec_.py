# Copyright 2026 Cloudsmith Ltd
"""CLI/Commands - Run a command with Cloudsmith credentials provisioned."""

import sys

import click

from ...credential_helpers.shellplugin import runner
from ..decorators import common_api_auth_options, resolve_credentials
from .main import main


@main.command(name="exec", context_settings={"ignore_unknown_options": True})
@click.option(
    "--org", default=None, envvar="CLOUDSMITH_ORG", help="Cloudsmith organisation slug."
)
@click.option(
    "--repo", default=None, envvar="CLOUDSMITH_REPO", help="Cloudsmith repository slug."
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
@common_api_auth_options
@resolve_credentials
def exec_(opts, org, repo, command):
    """Run a package-manager command authenticated against Cloudsmith.

    Wraps the command so it resolves dependencies from (and publishes to) your
    Cloudsmith repository, with credentials injected for that single run and
    cleaned up afterwards. The package manager is detected automatically from
    the command, so just put it after ``--``:

    \b
        $ cloudsmith exec -- mvn clean deploy
    """
    exit_code = runner.run(
        list(command),
        credential=opts.credential,
        owner=org,
        repo=repo,
        api_host=opts.api_host,
    )
    sys.exit(exit_code)
