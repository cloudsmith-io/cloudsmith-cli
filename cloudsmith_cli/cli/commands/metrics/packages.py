# -*- coding: utf8 -*-
"""CLI/Commands - retrieve metrics."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from ....core.api import metrics as api
from ... import decorators, utils, validators
from ...exceptions import handle_api_exceptions
from ...utils import maybe_spinner
from .command import metrics


def _print_total_usage_table(opts, data):
    """ Print total usage metrics as a table. """
    headers = [
        "Total Downloads",
        "Active Packages",
        "Inactive Packages",
        "Total Packages",
    ]

    click.echo(click.style("\nPackage Usage Totals", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    rows = []
    rows.append(
        [
            click.style(str(data.get("total_downloads", 0)), fg="blue"),
            click.style(str(data.get("active_packages", 0)), fg="green"),
            click.style(str(data.get("inactive_packages", 0)), fg="red"),
            click.style(str(data.get("total_packages", 0)), fg="white"),
        ]
    )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()


def _print_statistics_table(opts, data):
    """ Print usage metrics as a table. """
    headers = ["Lowest usage", "Average usage", "Highest usage"]

    click.echo(click.style("Package Usage Statistics", bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    rows = []
    rows.append(
        [
            click.style(str(data.get("lowest", 0)), fg="white"),
            click.style(str(data.get("average", 0)), fg="white"),
            click.style(str(data.get("highest", 0)), fg="white"),
        ]
    )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()


def _print_packages(opts, data, label):
    """ Print packages metrics as a table. """
    headers = ["Name", "Version", "Slug"]

    click.echo(click.style(label, bold=True, fg="white"))
    click.echo(
        "---------------------------------------------------------------", nl=False
    )

    rows = []
    for metric in data:
        rows.append(
            [
                click.style(str(metric.name), fg="white"),
                click.style(str(metric.version), fg="white"),
                click.style(str(metric.slug), fg="white"),
            ]
        )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()


@metrics.command(name="packages", aliases=["packages"])
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
    "--packages",
    type=str,
    required=False,
    help="A comma seperated list of packages (identifiers). Each identifier is exactly 12 characters in "
    "length and only contain alphanumerics. If a list is not specified then "
    "all packages will be included for a given repository.",
    callback=validators.validate_optional_tokens,
)
@click.option(
    "--start",
    type=str,
    required=False,
    help="A UTC timestamp used to filter metrics starting from this period.",
    callback=validators.validate_optional_timestamp,
)
@click.option(
    "--finish",
    type=str,
    required=False,
    help="A UTC timestamp used to filter metrics ending before this period.",
    callback=validators.validate_optional_timestamp,
)
@click.option(
    "--active-packages",
    type=bool,
    required=False,
    help="A boolean flag used to include active packages.",
)
@click.option(
    "--inactive-packages",
    type=bool,
    required=False,
    help="A boolean flag used to include inactive packages.",
)
@click.pass_context
def usage(
    ctx, opts, owner_repo, packages, start, finish, active_packages, inactive_packages
):
    """
    Retrieve package usage metrics.

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
            metrics_ = api.package_usage_metrics(
                owner=owner, repo=repo, packages=packages, start=start, finish=finish
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, metrics_):
        return

    _print_total_usage_table(opts=opts, data=metrics_.totals)
    _print_statistics_table(opts=opts, data=metrics_.downloads_per_package)
    if active_packages:
        _print_packages(
            opts=opts, data=metrics_.active_packages, label="Active Packages"
        )
    if inactive_packages:
        _print_packages(
            opts=opts, data=metrics_.inactive_packages, label="Inactive Packages"
        )
