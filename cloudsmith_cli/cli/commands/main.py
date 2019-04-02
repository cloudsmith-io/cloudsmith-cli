# -*- coding: utf-8 -*-
"""Main command/entrypoint."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from ...core.api.version import get_version as get_api_version
from ...core.utils import get_github_website, get_help_website
from ...core.version import get_version as get_cli_version
from .. import command, decorators

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def print_version():
    """Print the environment versions."""
    click.echo("Versions:")
    click.secho(
        "CLI Package Version: %(version)s"
        % {"version": click.style(get_cli_version(), bold=True)}
    )
    click.secho(
        "API Package Version: %(version)s"
        % {"version": click.style(get_api_version(), bold=True)}
    )


@click.group(
    cls=command.AliasGroup,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    help="""\b
   ________                __               _ __  __       ________    ____
  / ____/ /___  __  ______/ /________ ___  (_) /_/ /_     / ____/ /   /  _/
 / /   / / __ \\/ / / / __  / ___/ __ `__ \\/ / __/ __ \\   / /   / /    / /
/ /___/ / /_/ / /_/ / /_/ (__  ) / / / / / / /_/ / / /  / /___/ /____/ /
\\____/_/\\____/\\__,_/\\__,_/____/_/ /_/ /_/_/\\__/_/ /_/   \\____/_____/___/


The Cloudsmith Command-Line Interface - Be Awesome. Automate Everything.
    """,
    epilog="""
For more help, see the docs: %(help_website)s

For issues/contributing: %(github_website)s
    """
    % {"help_website": get_help_website(), "github_website": get_github_website()},
)
@click.option(
    "-V",
    "--version",
    help="Show the version numbers for the API and CLI.",
    is_flag=True,
    is_eager=True,
)
@decorators.common_cli_config_options
@click.pass_context
def main(ctx, opts, version):
    """Handle entrypoint to CLI."""
    # pylint: disable=unused-argument
    if version:
        print_version()
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
