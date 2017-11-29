"""Main command/entrypoint."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from . import main


@main.command()
@click.pass_context
def help(ctx):
    """Show this message and exit."""
    click.echo(ctx.parent.get_help())
