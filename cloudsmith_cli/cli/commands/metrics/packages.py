# -*- coding: utf-8 -*-
"""CLI/Commands - retrieve metrics."""
from __future__ import absolute_import, print_function, unicode_literals

import click
import six

from ....core.api import metrics as api
from ... import decorators, utils, validators
from ...exceptions import handle_api_exceptions
from ...utils import maybe_spinner
from .command import metrics


def _print_activity_table(opts, data):
    """Print token activity as a table."""
    utils.pretty_print_table(
        headers=["Active", "Inactive", "Total"],
        rows=[
            [
                click.style(str(data.get(k, 0)), fg="green")
                for k in ("active", "inactive", "total")
            ]
        ],
        title="Activity Summary (Active = Has Downloads)",
    )

    click.echo()


def _print_metrics_table(opts, data):
    """Print metrics as a table. """
    category_keys = {"Bandwidth": "bandwidth", "Downloads": "downloads"}

    metrics_keys = {
        "Average": "average",
        "Lowest": "lowest",
        "Highest": "highest",
        "Total": "total",
    }

    headers = ["Metric", *six.iterkeys(metrics_keys)]
    rows = []

    for category_header, category_key in six.iteritems(category_keys):
        category_data = data.get(category_key)
        cols = [category_header]
        for metric_key in six.itervalues(metrics_keys):
            metric_data = category_data.get(metric_key, {})
            if "display" in metric_data:
                value = metric_data.get("display")
            else:
                value = metric_data.get("value")
            value = str(value or 0)
            cols.append(click.style(value, fg="green"))
        rows.append(cols)

    utils.pretty_print_table(headers=headers, rows=rows, title="Entitlement Metrics")

    click.echo()


@metrics.command(name="packages", aliases=["pkgs"])
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
    help=(
        "A comma seperated list of package identifiers (i.e. slug_perm). "
        "If a list is not specified then all package will be included for "
        "a given repository."
    ),
)
@click.option(
    "--start",
    type=str,
    required=False,
    help=(
        "Include metrics from and including this UTC date or UTC datetime. "
        "For example '2020-12-31' or '2021-12-13T00:00:00Z'."
    ),
)
@click.option(
    "--finish",
    type=str,
    required=False,
    help=(
        "Include metrics up to and including this UTC date or UTC datetime. "
        "For example '2020-12-31' or '2021-12-13T00:00:00Z'."
    ),
)
@click.pass_context
def usage(ctx, opts, owner_repo, packages, start, finish):
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
            data = api.get_repository_packages_metrics(
                owner=owner, repo=repo, packages=packages, start=start, finish=finish
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, data):
        return

    click.echo()

    _print_activity_table(opts, data)
    _print_metrics_table(opts, data)
