"""CLI/Commands - Overages."""

import click

from .. import command, decorators, validators, utils
from .main import main
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from ...core.api import overages as api


# @main.group(cls=command.AliasGroup, name="overages", aliases=[])
@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner", metavar="OWNER", callback=validators.validate_owner, required=True
)
@click.pass_context
def overages(ctx, opts, owner):  # pylink: disable=unused-argument
    # """
    # Display Usage Limit Overages for an organisation.

    # See the help for subcommands for more information on each.
    # """
    """
    Retrieve Storage and Bandwidth Overages.

    This requires appropriate permissions for the owner (a member of the
    organisation and a valid API key).

    - OWNER: Specify the OWNER namespace (i.e. org)

      Example: 'your-org'

    Full CLI example:

      $ cloudsmith overages your-org
    """
    click.echo("Getting overages ... ", nl=False)

    owner = owner[0]
    context_msg = "Failed to get overages!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            overages_ = api.overages(owner=owner)

    click.secho("OK", fg="green")

    if utils.maybe_print_as_json(opts, overages_):
        return
    
    click.secho(overages_) # TEMP
    
