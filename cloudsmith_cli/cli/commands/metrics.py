# -*- coding: utf8 -*-
"""CLI/Commands - retrieve metrics."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from ...core.api import metrics as api
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def _print_total_usage_table(opts, data):
    """ Print total usage metrics as a table. """
    headers = ["Total Tokens", "Active Tokens", "Inactive Tokens", "Bandwidth Used"]

    click.echo(click.style("\nUsage Totals", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    rows = []
    rows.append(
        [
            click.style(str(data.totals.get("tokens", 0)), fg="blue"),
            click.style(str(data.totals.get("active_tokens", 0)), fg="green"),
            click.style(str(data.totals.get("inactive_tokens", 0)), fg="red"),
            click.style(str(data.totals.get("bandwidth_used", 0)), fg="white"),
        ]
    )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()


def _print_bandwith_usage_table(opts, data):
    """ Print bandwidth usage metrics as a table. """
    headers = ["Lowest usage", "Average usage", "Highest usage"]

    click.echo(click.style("Bandwidth Usage Statistics", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    rows = []
    rows.append(
        [
            click.style(str(data.bandwidth_per_token.get("lowest", 0)), fg="white"),
            click.style(str(data.bandwidth_per_token.get("average", 0)), fg="white"),
            click.style(str(data.bandwidth_per_token.get("highest", 0)), fg="white"),
        ]
    )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()


def print_metrics(opts, data):
    """ Print metrics as a table or output in another format. """
    _print_total_usage_table(opts, data)
    _print_bandwith_usage_table(opts, data)


@main.group(cls=command.AliasGroup, name="metrics", aliases=["metrics"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def metrics(ctx, opts):  # pylink: disable=unused-argument
    """
    Retrieve Metrics.

    See the help for subcommands for more information on each.
    """


@metrics.command(name="usage", aliases=["usage"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo",
    metavar="OWNER/REPO",
    callback=validators.validate_owner_repo,
    required=True,
)
@click.option(
    "--tokens",
    type=str,
    required=False,
    help="A comma seperated list of entitlement tokens (identifiers). Each identifier is exactly 12 characters in "
    "length and only contain alphanumerics. If a list is not specified then "
    "all entitlement tokens will be included for a given repository.",
    callback=validators.validate_optional_tokens,
)
@click.option(
    "--start",
    type=str,
    required=False,
    help="An utc timestamp used to filter metrics starting from this period.",
    callback=validators.validate_optional_timestamp,
)
@click.option(
    "--finish",
    type=str,
    required=False,
    help="An utc timestamp used to filter metrics ending before this period.",
    callback=validators.validate_optional_timestamp,
)
@click.pass_context
def usage(ctx, opts, owner_repo, tokens, start, finish):
    """
    Retrieve metrics for a namespace (owner).

    OWNER/REPO: Specify the OWNER namespace (i.e user or org) and repository to retrieve the
    metrics for that namespace/repository combination.
    """
    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo("Getting usage metrics ... ", nl=False, err=use_stderr)

    owner = None
    repo = None
    # owner/repo are required arguments
    if isinstance(owner_repo, list) and len(owner_repo) == 2:
        owner, repo = owner_repo

    context_msg = "Failed to get list of metrics!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            metrics_ = api.usage_metrics(
                owner=owner, repo=repo, tokens=tokens, start=start, finish=finish
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, metrics_):
        return

    print_metrics(opts=opts, data=metrics_)
