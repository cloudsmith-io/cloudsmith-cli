"""CLI/Commands - Authenticate the user."""

import webbrowser

import click

from ...core.api import exceptions, user
from ...core.api.init import initialise_api
from ...core.config import create_config_files, new_config_messaging
from .. import decorators, validators
from ..exceptions import handle_api_exceptions
from ..saml import create_configured_session, get_idp_url
from ..utils import maybe_spinner
from ..webserver import AuthenticationWebRequestHandler, AuthenticationWebServer
from .main import main


@main.command(aliases=["auth"])
@click.option(
    "-o",
    "--owner",
    metavar="OWNER",
    required=True,
    callback=validators.validate_owner,
    prompt=True,
    help="The name of the Cloudsmith organization to authenticate with.",
)
@click.option(
    "-t",
    "--token",
    default=False,
    is_flag=True,
    help="Retrieve a user API token after successful authentication.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def authenticate(ctx, opts, owner, token):
    """Authenticate to Cloudsmith using the org's SAML setup."""
    owner = owner[0].strip("'[]'")
    api_host = opts.api_config.host

    click.echo(
        "Beginning authentication for the {owner} org ... ".format(
            owner=click.style(owner, bold=True)
        )
    )

    session = create_configured_session(opts)

    context_message = "Failed to authenticate via SSO!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_message):
        idp_url = get_idp_url(api_host, owner, session=session)
        click.echo(
            "Opening your organization's SAML IDP URL in your browser: %(idp_url)s"
            % {"idp_url": click.style(idp_url, bold=True)}
        )
        click.echo()
        webbrowser.open(idp_url)
        click.echo("Starting webserver to begin authentication ... ")

        auth_server = AuthenticationWebServer(
            ("127.0.0.1", 12400),
            AuthenticationWebRequestHandler,
            api_host=api_host,
            owner=owner,
            session=session,
            debug=opts.debug,
        )
        auth_server.handle_request()

        if not token:
            return

        initialise_api()
        try:
            api_token = user.create_user_token_saml()
            click.echo(f"New token value: {click.style(api_token.key, fg='magenta')}")
            create, has_errors = create_config_files(ctx, opts, api_key=api_token.key)
            new_config_messaging(has_errors, opts, create, api_key=api_token.key)
            return
        except exceptions.ApiException as exc:
            if exc.status == 400:
                if "User has already created an API key" in exc.detail:
                    click.confirm(
                        "User already has a token. Would you like to recreate it?",
                        abort=True,
                    )
                else:
                    raise

        context_msg = "Failed to refresh the token!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            api_tokens = user.list_user_tokens()
        for t in api_tokens:
            click.echo("Current tokens:")
            click.echo(
                f"Token: {click.style(t.key, fg='magenta')}, "
                f"Created: {click.style(t.created, fg='green')}, "
                f"slug_perm: {click.style(t.slug_perm, fg='cyan')}"
            )
        token_slug = click.prompt(
            "Please enter the slug_perm of the token you would like to refresh"
        )

        click.echo(f"Refreshing token {token_slug}... ", nl=False)
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                new_token = user.refresh_user_token(token_slug)
        click.secho("OK", fg="green")
        click.echo(f"New token value: {click.style(new_token.key, fg='magenta')}")
        create, has_errors = create_config_files(ctx, opts, api_key=new_token.key)
        new_config_messaging(has_errors, opts, create, api_key=new_token.key)
