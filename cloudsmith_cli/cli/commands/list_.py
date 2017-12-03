"""CLI/Commands - List objects."""
from __future__ import absolute_import, print_function, unicode_literals

from operator import attrgetter, itemgetter

import click
from click_didyoumean import DYMGroup
from click_spinner import spinner

from . import main
from .. import decorators, validators
from ...core.api.distros import list_distros
from ...core.api.packages import (
    get_package_format_names_with_distros, list_packages
)
from ...core.api.repos import list_repos
from ..exceptions import handle_api_exceptions


@main.group(
    cls=DYMGroup,
    name='list')
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

    if distros_:
        distro_name_max = max(len(distro.name) for distro in distros_)
        distro_name_max = max(distro_name_max, len('Distro Name'))
        format_name_max = max(
            len(x) for x in get_package_format_names_with_distros()
        )
        format_name_max = max(format_name_max, len('Format'))
        release_name_max = max(
            len(release.name)
            for distro in distros_
            for release in distro.versions
            if release
        )
        release_name_max = max(release_name_max, len('Release Name'))

    # pylint: disable=fixme
    # TODO(ls): Add in custom sorting and filtering.
    for distro in sorted(distros_, key=attrgetter('slug')):
        if not distro.versions:
            continue

        click.echo()
        click.secho(
            '%(distro_name)s%(format_col)s | %(release_name)s | %(slug)s' % {
                'distro_name': click.style(
                    'Distro Name'.ljust(distro_name_max), bold=True),
                'format_col': (
                    ' | %s' % click.style(
                        'Format'.ljust(format_name_max), bold=True)
                    if not package_format else ''
                ),
                'release_name': click.style(
                    'Release Name'.ljust(release_name_max), bold=True),
                'slug': click.style('Slug', bold=True),
            }
        )

        for release in sorted(distro.versions, key=attrgetter('slug')):
            click.secho(
                '%(distro_name)s%(format_col)s | %(name)s |'
                ' %(distro_slug)s/%(slug)s' % {
                    'distro_name': click.style(
                        distro.name.ljust(distro_name_max), fg='blue'),
                    'format_col': (
                        ' | %s' % click.style(
                            distro.format.ljust(format_name_max), fg='blue')
                        if not package_format else ''
                    ),
                    'name': click.style(
                        release.name.ljust(release_name_max), fg='cyan'
                    ),
                    'distro_slug': click.style(distro.slug, fg='green'),
                    'slug': click.style(release.slug, fg='magenta'),
                }
            )

    num_distros = sum(
        1
        for distro in distros_
        for release in distro.versions
        if release
    )

    click.echo()
    click.secho(
        'Total: %(num)s distribution release%(plural)s' % {
            'num': click.style(
                str(num_distros),
                fg='green' if num_distros > 0 else 'red'
            ),
            'plural': 's' if num_distros != 1 else ''
        }
    )


@list_.command()
@click.argument(
    'owner_repo', metavar='OWNER/REPO',
    callback=validators.validate_owner_repo)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def packages(ctx, opts, owner_repo):
    """
    List packages for a repository.

    OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
    REPO name to list packages for that namespace and repository. All separated
    by a slash.
    """
    owner, repo = owner_repo

    click.echo(
        'Getting list of packages ... ', nl=False
    )

    context_msg = 'Failed to get list of packages!'
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            packages_ = list_packages(owner=owner, repo=repo)

    click.secho('OK', fg='green')

    if packages_:
        click.echo()
        package_name_max = max(
            len(_get_package_name(package))
            for package in packages_
        )
        package_name_max = max(package_name_max, len('Name'))

        package_status_max = max(
            len(_get_package_status(package))
            for package in packages_
        )
        package_status_max = max(package_status_max, len('Status'))

        package_version_max = max(
            len(_get_package_version(package))
            for package in packages_ if package['version']
        )
        package_version_max = max(package_version_max, len('Version'))

        # pylint: disable=fixme
        # FIXME(ls): Add a utility for printing out tables?
        click.secho(
            '%(name)s | %(version)s | %(status)s | %(slug)s' % {
                'name':
                    click.style('Name'.ljust(package_name_max), bold=True),
                'version':
                    click.style(
                        'Version'.ljust(package_version_max), bold=True),
                'status':
                    click.style(
                        'Status'.ljust(package_status_max), bold=True),
                'slug': click.style('Slug', bold=True)
            }
        )

    for package in sorted(packages_, key=itemgetter('slug')):
        click.secho(
            '%(name)s | %(version)s | %(status)s | '
            '%(owner_slug)s/%(repo_slug)s/%(slug)s' % {
                'name': click.style(
                    _get_package_name(package)
                    .ljust(package_name_max), fg='blue'
                ),
                'owner_slug': click.style(package['namespace'], fg='green'),
                'repo_slug': click.style(package['repository'], fg='green'),
                'slug': click.style(package['slug'], fg='magenta'),
                'status': click.style(
                    _get_package_status(package)
                    .ljust(package_status_max), fg='cyan'
                ),
                'version': click.style(
                    (_get_package_version(package))
                    .ljust(package_version_max), fg='blue'
                ),
            }
        )

    click.echo()
    click.secho(
        'Total: %(num)s package%(plural)s visible' % {
            'num': click.style(
                str(len(packages_)),
                fg='green' if packages_ else 'red'
            ),
            'plural': 's' if len(packages_) != 1 else ''
        }
    )


@list_.command()
@click.argument(
    'owner', default=None, required=False)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def repos(ctx, opts, owner):
    """
    List repositories for a namespace (owner).

    OWNER: Specify the OWNER namespace (i.e. user or org) to list the
    repositories for that namespace.

    If OWNER isn't specified it'll default to the currently authenticated user
    (if any). If you're unauthenticated, no results will be returned.
    """
    click.echo(
        'Getting list of repositories ... ', nl=False
    )

    context_msg = 'Failed to get list of repositories!'
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            repos_ = list_repos(owner=owner)

    click.secho('OK', fg='green')

    if repos_:
        click.echo()
        repo_name_max = max(len(repo['name']) for repo in repos_)
        repo_name_max = max(repo_name_max, len('Name'))
        repo_type_max = max(
            len(repo['repository_type_str']) for repo in repos_
        )
        repo_type_max = max(repo_type_max, len('Type'))

        click.secho(
            '%(name)s | %(type)s | %(slug)s' % {
                'name': click.style(
                    'Name'.ljust(repo_name_max), bold=True
                ),
                'slug': click.style(
                    'Slug', bold=True
                ),
                'type': click.style(
                    'Type'.ljust(repo_type_max), bold=True)
            }
        )

    for repo in sorted(repos_, key=itemgetter('slug')):
        click.secho(
            '%(name)s | %(type)s | %(owner_slug)s/%(slug)s' % {
                'name': click.style(
                    repo['name'].ljust(repo_name_max), fg='blue'
                ),
                'owner_slug': click.style(repo['namespace'], fg='green'),
                'slug': click.style(repo['slug'], fg='magenta'),
                'type': click.style(
                    repo['repository_type_str']
                    .ljust(repo_type_max), fg='cyan')
            }
        )

    click.echo()
    click.secho(
        'Total: %(num)s repositor%(plural)s visible' % {
            'num': click.style(
                str(len(repos_)),
                fg='green' if repos_ else 'red'
            ),
            'plural': 'ies' if len(repos_) != 1 else 'y'
        }
    )


def _get_package_name(package):
    """Get the name (or filename) for a package."""
    return package['name'] or package['filename']


def _get_package_status(package):
    """Get the status for a package."""
    status = package['status_str'] or 'Unknown'
    stage = package['stage_str'] or 'Unknown'
    if stage == 'Fully Synchronised':
        return status
    return '%(status)s / %(stage)s' % {
        'status': status,
        'stage': stage
    }


def _get_package_version(package):
    """Get the version for a package (if any)."""
    return package['version'] or 'None'
