"""CLI/Commands - Authenticate the user."""

import webbrowser

import click

from .. import decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..saml import create_configured_session, get_idp_url
from ..webserver import AuthenticationWebRequestHandler, AuthenticationWebServer
from .main import main
from .tokens import create, request_api_key

# Authentication server configuration
AUTH_SERVER_HOST = "127.0.0.1"
AUTH_SERVER_PORT = 12400


def _perform_saml_authentication(
    opts, owner, enable_token_creation=False, use_stderr=False
):
    """Perform SAML authentication via web browser and local web server."""
    session = create_configured_session(opts)
    api_host = opts.api_config.host

    idp_url = get_idp_url(api_host, owner, session=session)

    click.echo(
        f"Opening your organization's SAML IDP URL in your browser: {click.style(idp_url, bold=True)}",
        err=use_stderr,
    )
    click.echo(err=use_stderr)
    webbrowser.open(idp_url)

    click.echo("Starting webserver to begin authentication ... ", err=use_stderr)

    auth_server = AuthenticationWebServer(
        (AUTH_SERVER_HOST, AUTH_SERVER_PORT),
        AuthenticationWebRequestHandler,
        owner=owner,
        session=session,
        debug=opts.debug,
        refresh_api_on_success=enable_token_creation,
        api_opts=opts.api_config,
    )

    auth_server.handle_request()


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
    help="[DEPRECATED: Use --request-api-key] Retrieve a user API token after successful authentication.",
)
@click.option(
    "-f",
    "--force",
    default=False,
    is_flag=True,
    help="[DEPRECATED: Use --request-api-key] Force refresh of user API token without prompts.",
)
@click.option(
    "--save-config",
    default=False,
    is_flag=True,
    help="Save the new API key to your configuration files.",
)
@click.option(
    "--json",
    default=False,
    is_flag=True,
    help="Output token details in json format.",
)
@click.option(
    "--request-api-key",
    "request_api_key_flag",
    default=False,
    is_flag=True,
    help="Retrieve API token (auto-creates or auto-rotates, no prompts). "
    "Warning: If token exists, this will rotate it and invalidate the old key.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def authenticate(
    ctx, opts, owner, token, force, save_config, json, request_api_key_flag
):
    """Authenticate to Cloudsmith using the org's SAML setup."""
    # Validate mutual exclusivity
    if request_api_key_flag and (token or force):
        raise click.UsageError(
            "--request-api-key cannot be used with --token or --force. "
            "Use --request-api-key alone for fully automated token retrieval."
        )

    # Determine if we should redirect info messages to stderr
    use_stderr = request_api_key_flag or json or utils.should_use_stderr(opts)

    if token:
        click.secho(
            "DEPRECATION WARNING: The `--token` flag is deprecated and will be removed in a future release. "
            "Please use `--request-api-key` instead.",
            fg="yellow",
            err=True,
        )

    if force:
        click.secho(
            "DEPRECATION WARNING: The `--force` flag is deprecated and will be removed in a future release. "
            "Please use `--request-api-key` instead (force is implied).",
            fg="yellow",
            err=True,
        )

    if json and not utils.should_use_stderr(opts):
        click.secho(
            "DEPRECATION WARNING: The `--json` flag is deprecated and will be removed in a future release. "
            "Please use `--output-format json` instead.",
            fg="yellow",
            err=True,
        )

    owner = owner[0].strip("'[]'")

    click.echo(
        f"Beginning authentication for the {click.style(owner, bold=True)} org ... ",
        err=use_stderr,
    )

    # Determine if we need to refresh API after SSO (required for token operations)
    enable_token_creation = token or request_api_key_flag

    context_message = "Failed to authenticate via SSO!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_message):
        _perform_saml_authentication(
            opts,
            owner,
            enable_token_creation=enable_token_creation,
            use_stderr=use_stderr,
        )

    if request_api_key_flag:
        # Non-interactive token retrieval
        new_token = request_api_key(ctx, opts, save_config=save_config)

        if not new_token:
            raise click.ClickException(
                "Failed to retrieve API token. No token was returned."
            )

        # Check if JSON output is requested
        if utils.maybe_print_as_json(opts, new_token):
            return

        # Default: output only the raw token value to stdout
        click.echo(new_token.key)
        return

    if token:
        ctx.invoke(create, opts=opts, save_config=save_config, force=force, json=json)
