"""CLI - Validators."""
from __future__ import absolute_import, print_function, unicode_literals

import click


def validate_slashes(param, value, minimum=2, maximum=None, form=None):
    """Ensure that parameter has slashes and minimum parts."""
    try:
        value = value.split('/')
    except ValueError:
        value = None

    if value:
        if len(value) < minimum:
            value = None
        elif maximum and len(value) > maximum:
            value = None

    if not value:
        form = form or '/'.join('VALUE' for _ in range(minimum))
        raise click.BadParameter(
            'Must be in the form of %(form)s' % {'form': form},
            param=param)

    value = [v.strip() for v in value]
    if not all(value):
        raise click.BadParameter(
            'Individual values cannot be blank',
            param=param)

    return value


def validate_owner_repo(ctx, param, value):
    """Ensure that owner/repo is formatted correctly."""
    # pylint: disable=unused-argument
    form = 'OWNER/REPO'
    return validate_slashes(param, value, minimum=2, maximum=2, form=form)


def validate_owner_repo_package(ctx, param, value):
    """Ensure that owner/repo/package is formatted correctly."""
    # pylint: disable=unused-argument
    form = 'OWNER/REPO/PACKAGE'
    return validate_slashes(param, value, minimum=3, maximum=3, form=form)


def validate_owner_repo_distro(ctx, param, value):
    """Ensure that owner/repo/distro/version is formatted correctly."""
    # pylint: disable=unused-argument
    form = 'OWNER/REPO/DISTRO[/RELEASE]'
    return validate_slashes(param, value, minimum=3, maximum=4, form=form)
