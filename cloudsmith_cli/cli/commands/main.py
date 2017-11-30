"""Main command/entrypoint."""
from __future__ import absolute_import, print_function, unicode_literals

import click
from click_didyoumean import DYMGroup

from .. import decorators
from ...core.api.version import get_version as get_api_version
from ...core.utils import get_github_website, get_help_website
from ...core.version import get_version as get_cli_version


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def print_version():
    """Print the environment versions."""
    click.echo('Versions:')
    click.secho(
        'CLI Package Version: %(version)s' % {
            'version': click.style(get_cli_version(), bold=True)
        }
    )
    click.secho(
        'API Package Version: %(version)s' % {
            'version': click.style(get_api_version(), bold=True)
        }
    )


@click.group(
    cls=DYMGroup,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    help='The Cloudsmith CLI - Helping you to level up your DevOps!',
    epilog="""
For more help, see the docs: %(help_website)s

For issues/contributing: %(github_website)s
    """ % {
        'help_website': get_help_website(),
        'github_website': get_github_website()
    })
@click.option(
    '-V', '--version',
    help='Show the version numbers for the API and CLI.',
    is_flag=True, is_eager=True)
@decorators.common_cli_config_options
@click.pass_context
def main(ctx, opts, version):
    """Handle entrypoint to CLI."""
    # pylint: disable=unused-argument
    if version:
        print_version()
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
