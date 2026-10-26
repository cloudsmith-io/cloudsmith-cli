"""CLI/Commands - Get an API token."""

import click
import cloudsmith_api

from ...core.api.exceptions import TwoFactorRequiredException
from ...core.api.user import get_user_token
from ...core.config import create_config_files, new_config_messaging
from .. import decorators, utils
from ..exceptions import handle_api_exceptions
from ..usage_capture import TrackedCommand
from ..utils import maybe_spinner
from .main import main


def validate_login(ctx, param, value):
    """Ensure that login is not blank."""
    # pylint: disable=unused-argument
    value = value.strip()
    if not value:
        raise click.BadParameter("The value cannot be blank.", param=param)
    return value


#: Docs section on getting an API key and logging in with SAML instead.
API_KEY_DOCS_URL = (
    "https://docs.cloudsmith.com/developer-tools/cli#getting-your-api-key"
)

DEPRECATION_WARNING = (
    "Warning: `cloudsmith {name}` is deprecated and will stop working on "
    "November 20, 2026, when Cloudsmith disables username and password login. "
    "See https://cloudsmith.com/changelog\n"
    "Use an API key or SAML instead: set `CLOUDSMITH_API_KEY` to an API key from "
    "the Cloudsmith web app (your user menu, then Personal API Keys), or run "
    "`cloudsmith auth --workspace <workspace>` to log in with SAML.\n"
    f"More: {API_KEY_DOCS_URL}"
)


REMOVED_MESSAGE = (
    "Could not retrieve API key: username and password login is disabled.\n"
    "Fix: set `CLOUDSMITH_API_KEY` to an API key from the Cloudsmith web app "
    "(your user menu, then Personal API Keys), or run "
    "`cloudsmith auth --workspace <workspace>` to log in with SAML.\n"
    f"More: {API_KEY_DOCS_URL}"
)

#: Statuses the token endpoint returns once the server has disabled password
#: login (410) or deleted the route entirely (404).
REMOVED_STATUSES = (404, 410)


def summarise_removed_login(exc, detail, fields):
    """Replace the raw error with a clear notice once the endpoint is disabled."""
    # pylint: disable=unused-argument
    if exc.status in REMOVED_STATUSES:
        return REMOVED_MESSAGE
    return None


class DeprecatedLoginCommand(TrackedCommand):
    """Command that prints the deprecation warning before any prompt."""

    def parse_args(self, ctx, args):
        # Click prompts for --login and --password while parsing, so the
        # warning must be printed here rather than in the command body.
        # Shell completion also parses (resiliently) and must stay quiet.
        if not ctx.resilient_parsing:
            click.secho(
                DEPRECATION_WARNING.format(name=ctx.info_name), fg="yellow", err=True
            )
        return super().parse_args(ctx, args)


@main.command(cls=DeprecatedLoginCommand, aliases=["token"])
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
    """[DEPRECATED] Retrieve your API key with your email address and password.

    This command will stop working on November 20, 2026, when Cloudsmith
    disables username and password login. See https://cloudsmith.com/changelog

    Set `CLOUDSMITH_API_KEY` to an API key from the Cloudsmith web app instead,
    or run `cloudsmith auth --workspace <workspace>` to log in with SAML.

    More: https://docs.cloudsmith.com/developer-tools/cli#getting-your-api-key
    """
    use_stderr = utils.should_use_stderr(opts)
    click.echo(
        f"Retrieving API key for {click.style(login, bold=True)} ... ",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Could not retrieve API key"
    try:
        with (
            handle_api_exceptions(
                ctx,
                opts=opts,
                context_msg=context_msg,
                summarise_error=summarise_removed_login,
            ),
            maybe_spinner(opts),
        ):
            api_key = get_user_token(login=login, password=password)
    except TwoFactorRequiredException as e:
        click.echo("\r\033[K", nl=False, err=use_stderr)
        click.echo("Two-factor authentication is required.", err=use_stderr)

        totp_token = click.prompt(
            "Enter your two-factor authentication code", type=str, err=use_stderr
        )
        click.echo(
            f"Verifying two-factor code for {click.style(login, bold=True)} ... ",
            nl=False,
            err=use_stderr,
        )

        try:
            with (
                handle_api_exceptions(
                    ctx,
                    opts=opts,
                    context_msg=context_msg,
                    summarise_error=summarise_removed_login,
                ),
                maybe_spinner(opts),
            ):
                api_key = get_user_token(
                    login=login,
                    password=password,
                    totp_token=totp_token,
                    two_factor_token=e.two_factor_token,
                )
        except cloudsmith_api.rest.ApiException:
            click.echo("\r\033[K", nl=False, err=use_stderr)
            click.secho(
                "Authentication failed: The entered TOTP token is not valid.",
                fg="red",
                err=use_stderr,
            )
            ctx.exit(1)

    except cloudsmith_api.rest.ApiException as e:
        click.echo("\r\033[K", nl=False, err=use_stderr)
        click.secho(f"Authentication failed: {e!s}", fg="red", err=use_stderr)
        ctx.exit(1)

    click.secho("OK", fg="green", err=use_stderr)

    if not utils.maybe_print_as_json(opts, {"token": api_key, "login": login}):
        click.echo(
            "Your API key/token is: {token}".format(
                token=click.style(api_key, fg="magenta")
            )
        )

    create, has_errors = create_config_files(ctx, opts, api_key=api_key)
    new_config_messaging(has_errors, opts, create, api_key=api_key)
