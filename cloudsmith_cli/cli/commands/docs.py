"""CLI/Commands - Launch the help website."""
from __future__ import absolute_import, print_function, unicode_literals

import click
from ...core.utils import get_help_website
from .. import decorators
from . import main


@main.command()
@decorators.common_cli_config_options
@click.pass_context
def docs(ctx):
    """Launch the help website in your browser."""
    click.launch(get_help_website())
