"""CLI/Commands - Import all policy commands."""

import click

from ... import command, decorators
from ..main import main


@main.group(cls=command.AliasGroup, name="policy", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def policy(ctx, opts):  # pylink: disable=unused-argument
    """
    Manage policies for an organization.

    See the help for subcommands for more information on each.
    """
