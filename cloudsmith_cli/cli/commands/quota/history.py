"""CLI/Commands - List Quota History for Namespace."""

import click

from ....core.api import quota as api
from ... import decorators, utils, validators
from ...exceptions import handle_api_exceptions
from ...utils import maybe_spinner
from .command import quota


def display_history(opts, data):
    histories = data.history

    click.echo()
    click.echo(click.style("Quota History", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    headers = [
        "Plan",
        "Start",
        "End",
        "Days",
        "Uploaded",
        "Downloaded",
        "Download Limit",
        "Download Used",
        "Storage",
        "Storage Limit",
        "Storage Used",
    ]

    rows = []
    for history in histories:
        display = getattr(history, "display", {})
        uploaded = getattr(display, "uploaded", {})
        uploaded_used = getattr(uploaded, "used", "")

        downloaded = getattr(display, "downloaded", {})
        downloaded_used = getattr(downloaded, "used", "")
        downloaded_limit = getattr(downloaded, "limit", "")
        downloaded_percentage = getattr(downloaded, "percentage", "")

        storage = getattr(display, "storage_used", {})
        storage_used = getattr(storage, "used", "")
        storage_limit = getattr(storage, "limit", "")
        storage_percentage = getattr(storage, "percentage", "")

        history_start = str(history.start)[0:10]
        history_end = str(history.end)[0:10]

        rows.append(
            [
                click.style(str(history.plan), fg="green"),
                click.style(history_start, fg="white"),
                click.style(history_end, fg="white"),
                click.style(str(history.days), fg="white"),
                click.style(str(uploaded_used), fg="yellow"),
                click.style(str(downloaded_used), fg="cyan"),
                click.style(str(downloaded_limit), fg="white"),
                click.style(str(downloaded_percentage), fg="white"),
                click.style(str(storage_used), fg="magenta"),
                click.style(str(storage_limit), fg="white"),
                click.style(str(storage_percentage), fg="white"),
            ]
        )

    click.echo()
    utils.pretty_print_table(headers, rows)


@quota.command(name="history", aliases=[])
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
    Retrieve Quota history for namespace.

    This requires appropriate permissions for the owner (a member of the
    organisation and a valid API key).

    - OWNER: Specify the OWNER namespace (i.e. org)

      Example: 'your-org'

    Full CLI example:

      $ cloudsmith quota history your-org
    """

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"
    click.echo("Getting quota ... ", nl=False, err=use_stderr)

    owner = owner[0]

    context_msg = "Failed to get quota!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            quota_ = api.quota_history(owner=owner, oss=oss)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, quota_):
        return

    display_history(opts=opts, data=quota_)
