import click

from ...core.api import user as api
from .. import command, decorators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_print_as_json, maybe_spinner
from .main import main


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
    use_stderr = opts.output in ("json", "pretty_json")

    click.echo("Retrieving API tokens... ", nl=False, err=use_stderr)

    context_msg = "Failed to retrieve API tokens!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            tokens = api.list_user_tokens()
    click.secho("OK", fg="green", err=use_stderr)

    if maybe_print_as_json(opts, tokens):
        return

    print_tokens(tokens)


@tokens.command()
@click.argument(
    "token_slug",
    required=False,
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def refresh(ctx, opts, token_slug):
    """Refresh a specific API token by its slug."""
    context_msg = "Failed to refresh the token!"

    if not token_slug:
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                api_tokens = api.list_user_tokens()
        click.echo("Current tokens:")
        print_tokens(api_tokens)
        token_slug = click.prompt(
            "Please enter the slug_perm of the token you would like to refresh"
        )

    click.echo(f"Refreshing token {token_slug}... ", nl=False)
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            new_token = api.refresh_user_token(token_slug)
    click.secho("OK", fg="green")

    if maybe_print_as_json(opts, new_token):
        return

    click.echo(f"New token value: {click.style(new_token.key, fg='magenta')}")


def print_tokens(tokens):
    for token in tokens:
        click.echo(
            f"Token: {click.style(token.key, fg='magenta')}, "
            f"Created: {click.style(token.created, fg='green')}, "
            f"slug_perm: {click.style(token.slug_perm, fg='cyan')}"
        )
