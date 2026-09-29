"""CLI/Commands - Notice for the removed login and token commands."""

import click

from .main import main

REMOVAL_NOTICE = (
    "The 'cloudsmith login' and 'cloudsmith token' commands are no longer "
    "available. Username and password login is not supported.\n"
    "To authenticate, do one of these:\n"
    "  - Set the CLOUDSMITH_API_KEY environment variable to your API key.\n"
    "  - Run 'cloudsmith auth' to authenticate with SAML SSO."
)


@main.command(
    aliases=["token"],
    hidden=True,
    add_help_option=False,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def login(ctx):
    """Show a notice that the login and token commands are removed."""
    click.echo(REMOVAL_NOTICE, err=True)
    ctx.exit(1)
