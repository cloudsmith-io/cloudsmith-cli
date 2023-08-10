"""CLI/Commands - Get an API token."""

import click

from ...core.api.user import get_user_brief
from .. import decorators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def whoami(ctx, opts):
    """Retrieve your current authentication status."""
    click.echo("Retrieving your authentication status from the API ... ", nl=False)

    context_msg = "Failed to retrieve your authentication status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            is_auth, username, email, name = get_user_brief()
    click.secho("OK", fg="green")
    click.echo("You are authenticated as:")
    if not is_auth:
        click.secho("Nobody (i.e. anonymous user)", fg="yellow")
    else:
        click.secho(
            "%(name)s (slug: %(username)s"
            % {
                "name": click.style(name, fg="cyan"),
                "username": click.style(username, fg="magenta"),
            },
            nl=False,
        )

        if email:
            click.secho(
                f", email: {click.style(email, fg='green')}",
                nl=False,
            )

        click.echo(")")
