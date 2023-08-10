"""Main command/entrypoint."""

import click

from .main import main


@main.command(name="help")
@click.pass_context
def help_(ctx):
    """Show this delightful help message and exit."""
    click.echo(ctx.parent.get_help())
