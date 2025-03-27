"""CLI/Commands - Authenticate the user."""

import webbrowser

import click

from .. import decorators, validators
from ..exceptions import handle_api_exceptions
from ..saml import create_configured_session, get_idp_url
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
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def authenticate(ctx, opts, owner):
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
