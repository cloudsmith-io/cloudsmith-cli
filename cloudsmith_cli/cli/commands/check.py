"""CLI/Commands - Get an API token."""
from __future__ import absolute_import, print_function, unicode_literals

import click
from click_spinner import spinner
import semver
from ...core.api.status import get_status
from ...core.api.version import get_version as get_api_version_info
from .. import decorators
from ..exceptions import handle_api_exceptions
from . import main


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.initialise_api
@click.pass_context
def check(ctx, opts):
    """Check the status/version of the service."""
    click.echo("Retrieving service status ... ", nl=False)

    context_msg = "Failed to retrieve status!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            status, version = get_status(with_version=True)

    click.secho("OK", fg='green')

    click.echo(
        "The service status is: %(status)s" % {
            'status': click.style(status, bold=True)
        }
    )
    click.echo(
        "The service version is: %(version)s " % {
            'version': click.style(version, bold=True)
        }, nl=False
    )

    api_version = get_api_version_info()

    if semver.compare(version, api_version) > 0:
        click.secho(
            "(maybe out-of-date)",
            fg='yellow'
        )

        click.echo()
        click.secho(
            "The API library used by this CLI tool is built against "
            "service version: %(version)s" % {
                'version': click.style(api_version, bold=True)
            }, fg='yellow'
        )
    else:
        click.secho(
            "(up-to-date)",
            fg='green'
        )

        click.echo()
        click.secho(
            "The API library used by this CLI tool seems to be up-to-date.",
            fg='green'
        )
