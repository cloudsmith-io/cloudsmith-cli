# -*- coding: utf-8 -*-
"""Main command/entrypoint."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from .main import main


@main.command(name="help")
@click.pass_context
def help_(ctx):
    """Show this delightful help message and exit."""
    click.echo(ctx.parent.get_help())
