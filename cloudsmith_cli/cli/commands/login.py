"""CLI/Commands - Get an API token."""

import click
import cloudsmith_api

from ...core.api.exceptions import TwoFactorRequiredException
from ...core.api.user import get_user_token
from ...core.config import create_config_files, new_config_messaging
from .. import decorators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def validate_login(ctx, param, value):
    """Ensure that login is not blank."""
    # pylint: disable=unused-argument
    value = value.strip()
    if not value:
        raise click.BadParameter("The value cannot be blank.", param=param)
    return value


@main.command(aliases=["token"])
@click.option(
    "-l",
    "--login",
    required=True,
    callback=validate_login,
    prompt=True,
    help="Your Cloudsmith login account (email address).",
)
@click.password_option("-p", "--password", help="Your Cloudsmith login password.")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def login(ctx, opts, login, password):  # pylint: disable=redefined-outer-name
    """Retrieve your API authentication token/key via login."""
    click.echo(
        "Retrieving API token for %(login)s ... "
        % {"login": click.style(login, bold=True)},
        nl=False,
    )

    context_msg = "Failed to retrieve the API token!"
    try:
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                api_key = get_user_token(login=login, password=password)
    except TwoFactorRequiredException as e:
        click.echo("\r\033[K", nl=False)
        click.echo("Two-factor authentication is required.")

        totp_token = click.prompt("Enter your two-factor authentication code", type=str)
        click.echo(
            "Verifying two-factor code for %(login)s ... "
            % {"login": click.style(login, bold=True)},
            nl=False,
        )

        try:
            with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                with maybe_spinner(opts):
                    api_key = get_user_token(
                        login=login,
                        password=password,
                        totp_token=totp_token,
                        two_factor_token=e.two_factor_token,
                    )
        except cloudsmith_api.rest.ApiException:
            click.echo("\r\033[K", nl=False)
            click.secho(
                "Authentication failed: The entered TOTP token is not valid.", fg="red"
            )
            ctx.exit(1)

    except cloudsmith_api.rest.ApiException as e:
        click.echo("\r\033[K", nl=False)
        click.secho(f"Authentication failed: {str(e)}", fg="red")
        ctx.exit(1)

    click.secho("OK", fg="green")

    click.echo(
        "Your API key/token is: %(token)s"
        % {"token": click.style(api_key, fg="magenta")}
    )

    create, has_errors = create_config_files(ctx, opts, api_key=api_key)
    new_config_messaging(has_errors, opts, create, api_key=api_key)
