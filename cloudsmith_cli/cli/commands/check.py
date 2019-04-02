# -*- coding: utf-8 -*-
"""CLI/Commands - Get an API token."""
from __future__ import absolute_import, print_function, unicode_literals

import click
import cloudsmith_api
import semver
import six

from ...core.api.rates import get_rate_limits
from ...core.api.status import get_status
from ...core.api.version import get_version as get_api_version_info
from .. import command, decorators, utils
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.group(cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def check(ctx, opts):  # pylint: disable=unused-argument
    """Check rate limits and service status."""


@check.command(aliases=["limits"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def rates(ctx, opts):
    """Check current API rate limits."""
    click.echo("Retrieving rate limits ... ", nl=False)

    context_msg = "Failed to retrieve status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            resources_limits = get_rate_limits()

    click.secho("OK", fg="green")

    headers = ["Resource", "Throttled", "Remaining", "Interval (Seconds)", "Reset"]

    rows = []
    for resource, limits in six.iteritems(resources_limits):
        rows.append(
            [
                click.style(resource, fg="cyan"),
                click.style(
                    "Yes" if limits.throttled else "No",
                    fg="red" if limits.throttled else "green",
                ),
                "%(remaining)s/%(limit)s"
                % {
                    "remaining": click.style(
                        six.text_type(limits.remaining), fg="yellow"
                    ),
                    "limit": click.style(six.text_type(limits.limit), fg="yellow"),
                },
                click.style(six.text_type(limits.interval), fg="blue"),
                click.style(six.text_type(limits.reset), fg="magenta"),
            ]
        )

    if resources_limits:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(resources_limits)
    list_suffix = "resource%s" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@check.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def service(ctx, opts):
    """Check the status of the Cloudsmith service."""
    click.echo("Retrieving service status ... ", nl=False)

    context_msg = "Failed to retrieve status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            status, version = get_status(with_version=True)

    click.secho("OK", fg="green")

    config = cloudsmith_api.Configuration()

    click.echo()
    click.echo(
        "The service endpoint is: %(endpoint)s"
        % {"endpoint": click.style(config.host, bold=True)}
    )
    click.echo(
        "The service status is:   %(status)s"
        % {"status": click.style(status, bold=True)}
    )
    click.echo(
        "The service version is:  %(version)s "
        % {"version": click.style(version, bold=True)},
        nl=False,
    )

    api_version = get_api_version_info()

    if semver.compare(version, api_version) > 0:
        click.secho("(maybe out-of-date)", fg="yellow")

        click.echo()
        click.secho(
            "The API library used by this CLI tool is built against "
            "service version: %(version)s"
            % {"version": click.style(api_version, bold=True)},
            fg="yellow",
        )
    else:
        click.secho("(up-to-date)", fg="green")

        click.echo()
        click.secho(
            "The API library used by this CLI tool seems to be up-to-date.", fg="green"
        )
