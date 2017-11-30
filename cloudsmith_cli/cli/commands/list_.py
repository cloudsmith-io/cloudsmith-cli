"""CLI/Commands - List objects."""
from __future__ import absolute_import, print_function, unicode_literals

from operator import attrgetter

import click
from click_spinner import spinner

from . import main
from .. import decorators
from ...core.api.distros import list_distros
from ...core.api.packages import get_package_format_names_with_distros
from ..exceptions import handle_api_exceptions


@main.group(name='list')
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def list_(ctx, opts):  # pylint: disable=unused-argument
    """List distributions, packages and repos."""


@list_.command()
@click.argument(
    'package-format', default=None, required=False,
    type=click.Choice(get_package_format_names_with_distros()))
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def distros(ctx, opts, package_format):
    """List available distributions."""
    click.echo(
        'Getting list of distributions ... ', nl=False
    )

    context_msg = 'Failed to get list of distributions!'
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            distros_ = list_distros(package_format=package_format)

    click.secho('OK', fg='green')

    # pylint: disable=fixme
    # TODO(ls): Add in custom sorting and filtering.
    for distro in sorted(
            distros_, key=attrgetter('slug')):
        click.echo()
        click.secho(
            '%(distro)s : %(slug)s (%(format)s)' % {
                'distro': click.style(distro.name, fg='green'),
                'slug': click.style(distro.slug, fg='magenta'),
                'format': click.style(distro.format, bold=True)
            }
        )

        if not distro.versions:
            continue

        release_max = max(len(release.name) for release in distro.versions)
        for release in sorted(
                distro.versions, key=attrgetter('slug')):
            click.secho(
                ' - %(release)s : %(distro_slug)s/%(slug)s' % {
                    'release': click.style(
                        release.name.ljust(release_max), fg='blue'
                    ),
                    'distro_slug': click.style(distro.slug, fg='green'),
                    'slug': click.style(release.slug, fg='magenta'),
                }
            )
