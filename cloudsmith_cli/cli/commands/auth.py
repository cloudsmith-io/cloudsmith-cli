"""CLI/Commands - Authenticate the user."""
import webbrowser
from urllib.parse import urlencode

import click
import requests

from ...core.keyring import get_access_token, get_refresh_token
from .. import decorators, validators
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
    # TODO: Why is a single arg a list?
    owner = owner[0]

    # TODO: best way to consistently get API host?
    org_saml_url = "{api_host}/orgs/{owner}/saml/?".format(
        api_host=opts.api_config.host,
        owner=owner,
    )
    org_saml_url += urlencode({"redirect_url": "http://localhost:12400"})

    org_saml_response = requests.get(org_saml_url, timeout=30)
    idp_url = org_saml_response.json().get("redirect_url")

    click.echo(
        "Opening your organization's SAML IDP URL in your browser: %(idp_url)s"
        % {"idp_url": idp_url}
    )
    webbrowser.open(idp_url)
    click.echo("Starting webserver to begin authentication ... ")

    auth_server = AuthenticationWebServer(
        ("0.0.0.0", 12400),
        AuthenticationWebRequestHandler,
        api_host=opts.api_config.host,
        owner=owner,
    )
    auth_server.handle_request()

    click.echo()
    click.echo(f"Access token: {get_access_token()}")
    click.echo()
    click.echo(f"Refresh token: {get_refresh_token()}")
