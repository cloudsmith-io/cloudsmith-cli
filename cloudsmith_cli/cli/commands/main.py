"""Main command/entrypoint."""

import click

from ...core.api.version import get_version as get_api_version
from ...core.utils import get_github_website, get_help_website
from ...core.version import get_version as get_cli_version
from .. import command, decorators, utils
from .registry import LAZY_ALIASES, LAZY_COMMANDS

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def print_version(opts):
    """Print the environment versions."""
    cli_version = get_cli_version()
    api_version = get_api_version()

    data = {
        "cli_version": cli_version,
        "api_version": api_version,
    }

    if not utils.maybe_print_as_json(opts, data):
        click.echo("Versions:")
        click.secho(f"CLI Package Version: {click.style(cli_version, bold=True)}")
        click.secho(f"API Package Version: {click.style(api_version, bold=True)}")


@click.group(
    cls=command.AliasGroup,
    lazy_commands=LAZY_COMMANDS,
    lazy_aliases=LAZY_ALIASES,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    help="""\b
   ________                __               _ __  __       ________    ____
  / ____/ /___  __  ______/ /________ ___  (_) /_/ /_     / ____/ /   /  _/
 / /   / / __ \\/ / / / __  / ___/ __ `__ \\/ / __/ __ \\   / /   / /    / /
/ /___/ / /_/ / /_/ / /_/ (__  ) / / / / / / /_/ / / /  / /___/ /____/ /
\\____/_/\\____/\\__,_/\\__,_/____/_/ /_/ /_/_/\\__/_/ /_/   \\____/_____/___/


The Cloudsmith Command-Line Interface - Be Awesome. Automate Everything.
    """,
    epilog=f"""
For more help, see the docs: {get_help_website()}

For issues/contributing: {get_github_website()}
    """,
)
@click.option(
    "-V",
    "--version",
    help="Show the version numbers for the API and CLI.",
    is_flag=True,
    is_eager=True,
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@click.pass_context
def main(ctx, opts, version):
    """Handle entrypoint to CLI."""
    # pylint: disable=unused-argument

    if version:
        print_version(opts)
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
