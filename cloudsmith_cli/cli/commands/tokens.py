import click

from ...core.api import exceptions, user as api
from ...core.config import create_config_files, new_config_messaging
from .. import command, decorators, utils
from ..exceptions import handle_api_exceptions
from .main import main


def handle_duplicate_token_error(exc, ctx, opts, save_config, force, json):
    """
    Handle the case where user already has a token.

    Returns the token from refresh if user confirms, otherwise exits.
    """
    if (
        exc.status == 400
        and exc.detail
        and "User has already created an API key" in exc.detail
    ):
        if not force:
            if not click.confirm(
                "User already has a token. Would you like to recreate it?",
                abort=False,
                err=json,
            ):
                return None
        return refresh_existing_token_interactive(
            ctx, opts, save_config=save_config, force=force, json=json
        )
    raise exc


@main.group(cls=command.AliasGroup, name="tokens")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def tokens(ctx, opts):
    """Manage your user API tokens."""


@tokens.command(name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def list_tokens(ctx, opts):
    """List all user API tokens."""
    use_stderr = utils.should_use_stderr(opts)

    click.echo("Retrieving API tokens... ", nl=False, err=use_stderr)

    context_msg = "Failed to retrieve API tokens!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with utils.maybe_spinner(opts):
            tokens = api.list_user_tokens()
    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, tokens):
        return

    print_tokens(tokens)


@tokens.command()
@click.option(
    "--save-config",
    default=False,
    is_flag=True,
    help="Save the new API key to your configuration files.",
)
@click.option(
    "-f",
    "--force",
    default=False,
    is_flag=True,
    help="Force creation of user API token without prompts.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def create(ctx, opts, save_config, force=False, json=False):
    """Create a new API token."""
    new_token = _create(ctx, opts, save_config, force, json)

    if save_config:
        create, has_errors = create_config_files(
            ctx, opts, api_key=new_token.key, force=force
        )
        new_config_messaging(has_errors, opts, create, api_key=new_token.key)


@tokens.command()
@click.argument(
    "token_slug",
    required=False,
)
@click.option(
    "--save-config",
    default=False,
    is_flag=True,
    help="Save the new API key to your configuration files.",
)
@click.option(
    "-f",
    "--force",
    default=False,
    is_flag=True,
    help="Force refresh of user API token without prompts.",
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def refresh(ctx, opts, token_slug, force, save_config):
    """Refresh a specific API token by its slug."""
    new_token = refresh_existing_token_interactive(
        ctx, opts, token_slug, save_config, force
    )

    if new_token:
        if utils.maybe_print_as_json(opts, new_token):
            return new_token


def print_tokens(tokens):
    for token in tokens:
        click.echo(
            f"Token: {click.style(token.key, fg='magenta')}, "
            f"Created: {click.style(token.created, fg='green')}, "
            f"slug_perm: {click.style(token.slug_perm, fg='cyan')}"
        )


def refresh_existing_token_interactive(
    ctx, opts, token_slug=None, save_config=False, force=False, json=False
):
    """Refresh an existing API token with interactive token selection, or create new if none exist."""
    json = json or utils.should_use_stderr(opts)
    use_stderr = json
    context_msg = "Failed to refresh the token!"

    if not token_slug:
        try:
            with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                api_tokens = api.list_user_tokens()
        except exceptions.ApiException as exc:
            # If we can't list tokens due to API error, fall back to creating a new one
            if opts.debug:
                click.echo(f"Debug: Failed to list tokens with error: {exc}", err=True)
            click.echo(
                "Unable to list existing tokens. Creating a new token instead...",
                err=use_stderr,
            )
            return _create(ctx, opts, save_config=save_config, force=force, json=json)

        if not api_tokens:
            click.echo(
                "No existing tokens found. Creating a new token instead...",
                err=use_stderr,
            )
            return _create(ctx, opts, save_config=save_config, force=force, json=json)

        if not json:
            click.echo("Current tokens:")
            print_tokens(api_tokens)

        if not force:
            token_slug = click.prompt(
                "Please enter the slug_perm of the token you would like to refresh",
                err=use_stderr,
            )
        else:
            # Use the first available slug_perm when force is enabled
            token_slug = api_tokens[0].slug_perm
            if not json:
                click.echo(f"Using token {token_slug} (first available)")

    if not json:
        click.echo(f"Refreshing token {token_slug}... ", nl=False)
    else:
        # In JSON mode, print info to stderr
        click.echo(f"Refreshing token {token_slug}... ", nl=False, err=json)

    try:
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with utils.maybe_spinner(opts):
                new_token = api.refresh_user_token(token_slug)

        if save_config:
            create, has_errors = create_config_files(
                ctx, opts, api_key=new_token.key, force=force
            )
            new_config_messaging(has_errors, opts, create, api_key=new_token.key)

        if utils.maybe_print_as_json(opts, new_token):
            return

        if not json:
            click.secho("OK", fg="green")
            click.echo(f"New token value: {click.style(new_token.key, fg='magenta')}")

        return new_token
    except exceptions.ApiException as exc:
        # If refresh fails due to API error, offer to create a new token instead
        if opts.debug:
            click.echo(f"\nDebug: Refresh failed with error: {exc}", err=True)
        click.echo("\nRefresh failed. Creating a new token instead...", err=use_stderr)
        return _create(ctx, opts, save_config=save_config, force=force, json=json)


def _create(ctx, opts, save_config=False, force=False, json=False):
    """Create a new API token."""
    json = json or utils.should_use_stderr(opts)

    try:
        new_token = api.create_user_token_saml()

        if new_token:
            # NOTE: This mutation is necessary during the deprecation period of the --json flag.
            if json and opts.output not in ("json", "pretty_json"):
                opts.output = "json"

            if utils.maybe_print_as_json(opts, new_token):
                return

            click.echo(f"New token value: {click.style(new_token.key, fg='magenta')}")
            return new_token

        return new_token

    except exceptions.ApiException as exc:
        if exc.status == 401:
            click.echo(f"{exc.detail}", err=True)
            return
        # NOTE: This mutation is necessary during the deprecation period of the --json flag.
        if json and opts.output not in ("json", "pretty_json"):
            opts.output = "json"
        if exc.status == 400:
            new_token = handle_duplicate_token_error(
                exc, ctx, opts, save_config=save_config, force=force, json=json
            )
            return new_token
