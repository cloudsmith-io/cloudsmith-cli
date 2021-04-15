# -*- coding: utf-8 -*-
"""CLI/Commands - List Quota History for Namespace."""
from __future__ import absolute_import, print_function, unicode_literals

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

        uploaded = history.display.get("uploaded", {})
        uploaded_used = uploaded.get("used", "")

        downloaded = history.display.get("downloaded", {})
        downloaded_used = downloaded.get("used", "")
        downloaded_limit = downloaded.get("limit", "")
        downloaded_percentage = downloaded.get("percentage", "")

        storage = history.display.get("storage_used", {})
        storage_used = storage.get("used", "")
        storage_limit = storage.get("limit", "")
        storage_percentage = storage.get("percentage", "")

        rows.append(
            [
                click.style(str(history.plan), fg="green"),
                click.style(str(history.start[0:10]), fg="white"),
                click.style(str(history.end[0:10]), fg="white"),
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
