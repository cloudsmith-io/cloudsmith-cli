# -*- coding: utf-8 -*-
"""CLI/Commands - Import all Quota commands."""

import click

from ... import command, decorators
from ..main import main


@main.group(cls=command.AliasGroup, name="quota", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def quota(ctx, opts):  # pylink: disable=unused-argument
    """
    Display Quota limits and history for a organisation.

    See the help for subcommands for more information on each.
    """
