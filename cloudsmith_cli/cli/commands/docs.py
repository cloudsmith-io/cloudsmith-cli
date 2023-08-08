"""CLI/Commands - Launch the help website."""

import click

from ...core.utils import get_help_website
from .. import decorators
from .main import main


@main.command()
@decorators.common_cli_config_options
@click.pass_context
def docs(ctx, opts):
    """Launch the help website in your browser."""
    # pylint: disable=unused-argument
    click.launch(get_help_website())
