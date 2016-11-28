"""CLI/Commands - Get an API token."""
from __future__ import absolute_import, print_function, unicode_literals

import click
from click_spinner import spinner
from ...core.api.user import get_user_token
from .. import decorators
from ..exceptions import handle_api_exceptions
from . import main


def validate_login(ctx, param, value):
    """Ensure that login is not blank."""
    value = value.strip()
    if not value:
        raise click.BadParameter(
            "The value cannot be blank.", param=param)
    return value


@main.command()
@click.option(
    '-l', '--login', required=True, callback=validate_login, prompt=True,
    help="Your Cloudsmith login account (email address).")
@click.password_option(
    '-p', '--password',
    help="Your Cloudsmith login password.")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def token(ctx, opts, login, password):
    """Retrieve your API authentication token/key."""
    click.echo(
        "Retrieving API token for '%(login)s' ... " % {
            'login': click.style(login, bold=True)
        }, nl=False
    )

    context_msg = "Failed to retrieve the API token!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            token = get_user_token(
                login=login,
                password=password
            )

    click.secho("OK", fg='green')

    click.echo(
        "Your API token is: %(token)s" % {
            'token': click.style(token, bold=True)
        }
    )
