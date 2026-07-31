# Copyright 2026 Cloudsmith Ltd
"""CLI/Commands - Run a command with Cloudsmith credentials provisioned."""

import sys

import click
from click.core import ParameterSource

from ...credential_helpers.shellplugin import runner
from ..decorators import common_api_auth_options, resolve_credentials
from .main import main


@main.command(name="exec", context_settings={"ignore_unknown_options": True})
@click.option(
    "--org",
    default=None,
    envvar="CLOUDSMITH_ORG",
    help="Cloudsmith organisation slug. As a flag this overrides the stored "
    "binding; from the environment it applies only when nothing is stored.",
)
@click.option(
    "--repo",
    default=None,
    envvar="CLOUDSMITH_REPO",
    help="Cloudsmith repository slug. As a flag this overrides the stored "
    "binding; from the environment it applies only when nothing is stored.",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED, required=True)
@common_api_auth_options
@resolve_credentials
@click.pass_context
def exec_(ctx, opts, org, repo, command):
    """Run a package-manager command authenticated against Cloudsmith.

    Wraps the command so it resolves dependencies from (and publishes to) your
    Cloudsmith repository, with credentials injected for that single run and
    cleaned up afterwards. Maven runs use an ephemeral ``settings.xml``; your
    ``~/.m2/settings.xml`` is not consulted. The package manager is detected
    automatically from the command, so just put it after ``--``:

    \b
        $ cloudsmith exec -- mvn clean deploy
    """

    def flag_value(name, value):
        source = ctx.get_parameter_source(name)
        return value if source == ParameterSource.COMMANDLINE else None

    exit_code = runner.run(
        list(command),
        credential=opts.credential,
        owner=flag_value("org", org),
        repo=flag_value("repo", repo),
        default_owner=org,
        default_repo=repo,
    )
    sys.exit(exit_code)
