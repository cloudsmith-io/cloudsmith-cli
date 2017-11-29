"""CLI/Commands - Push packages."""
from __future__ import absolute_import, print_function, unicode_literals

import click
from click_spinner import spinner

from . import main
from .. import decorators, validators
from ...core.api.packages import delete_package
from ..exceptions import handle_api_exceptions


@main.command()
@click.argument(
    'owner_repo_package',
    metavar='OWNER/REPO/PACKAGE',
    callback=validators.validate_owner_repo_package)
@click.option(
    '-y', '--yes', default=False, is_flag=True,
    help='Assume yes as default answer to questions.')
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def delete(ctx, opts, owner_repo_package, yes):
    """
    Delete a package from a repository.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE name (slug) of the
    package itself. All separated by a slash.

    Example: 'your-org/awesome-repo/better-pkg'.
    """
    owner, repo, slug = owner_repo_package

    args = {
        'owner': click.style(owner, bold=True),
        'repo': click.style(repo, bold=True),
        'package': click.style(slug, bold=True)
    }

    if not yes and not click.confirm(
            'Are you sure you want to delete %(package)s from '
            '%(owner)s/%(repo)s?' % args):
        click.secho('OK! Phew, close call. :-)', fg='yellow')
        return

    click.echo(
        'Deleting %(package)s from %(owner)s/%(repo)s ... ' % args,
        nl=False
    )

    context_msg = 'Failed to delete the package!'
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            delete_package(
                owner=owner,
                repo=repo,
                slug=slug
            )

    click.secho('OK', fg='green')
