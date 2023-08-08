"""CLI/Commands - Display Quota for Namespace."""

import click

from ....core.api import quota as api
from ... import decorators, utils, validators
from ...exceptions import handle_api_exceptions
from ...utils import maybe_spinner
from .command import quota


def display_quota(opts, data):
    """Display Quota usage as a table."""
    display = getattr(data.usage, "display", {})
    bandwidth = getattr(display, "bandwidth", {})
    storage = getattr(display, "storage", {})

    click.echo()
    click.echo(click.style("Bandwidth Quota", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    headers = ["Bandwidth Used", "Configured", "Plan Limit", "Total Used"]
    rows = []
    rows.append(
        [
            click.style(str(getattr(bandwidth, "used", "")), fg="white"),
            click.style(str(getattr(bandwidth, "configured", "")), fg="white"),
            click.style(str(getattr(bandwidth, "plan_limit", "")), fg="white"),
            click.style(str(getattr(bandwidth, "percentage_used", "")), fg="white"),
        ]
    )
    click.echo()
    utils.pretty_print_table(headers, rows)

    click.echo()
    click.echo(click.style("Storage Quota", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    headers = ["Storage Used", "Configured", "Plan Limit", "Total Used"]
    rows = []
    rows.append(
        [
            click.style(str(getattr(storage, "used", "")), fg="white"),
            click.style(str(getattr(storage, "configured", "")), fg="white"),
            click.style(str(getattr(storage, "plan_limit", "")), fg="white"),
            click.style(str(getattr(storage, "percentage_used", "")), fg="white"),
        ]
    )
    click.echo()
    utils.pretty_print_table(headers, rows)

    click.echo()


@quota.command(name="limits", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner", metavar="OWNER", callback=validators.validate_owner, required=True
)
@click.option(
    "-oss",
    "--oss",
    default=False,
    is_flag=True,
    help="Shows the open source quota for a namespace",
)
@click.pass_context
def usage(ctx, opts, owner, oss):
    """
    Retrieve Quota limits.

    This requires appropriate permissions for the owner (a member of the
    organisation and a valid API key).

    - OWNER: Specify the OWNER namespace (i.e. org)

      Example: 'your-org'

    Full CLI example:

      $ cloudsmith quota limits your-org
    """

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"
    click.echo("Getting quota ... ", nl=False, err=use_stderr)

    owner = owner[0]

    context_msg = "Failed to get quota!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            quota_ = api.quota_limits(owner=owner, oss=oss)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, quota_):
        return

    display_quota(opts=opts, data=quota_)
