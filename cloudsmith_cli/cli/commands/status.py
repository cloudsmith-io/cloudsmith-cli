# -*- coding: utf-8 -*-
"""CLI/Commands - Push packages."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from ...core.api.packages import get_package_status
from .. import decorators, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.command()
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def status(ctx, opts, owner_repo_package):
    """
    Get the synchronisation status for a package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE name (slug) of the
    package itself. All separated by a slash.

    Example: 'your-org/awesome-repo/better-pkg'.
    """
    owner, repo, slug = owner_repo_package

    click.echo(
        "Getting status of %(package)s in %(owner)s/%(repo)s ... "
        % {
            "owner": click.style(owner, bold=True),
            "repo": click.style(repo, bold=True),
            "package": click.style(slug, bold=True),
        },
        nl=False,
    )

    context_msg = "Failed to get status of package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            res = get_package_status(owner, repo, slug)
            ok, failed, _, status_str, stage_str, reason = res

    click.secho("OK", fg="green")

    if not stage_str:
        package_status = status_str
    else:
        package_status = "%(status)s / %(stage)s" % {
            "status": status_str,
            "stage": stage_str,
        }

    if ok:
        status_colour = "green"
    elif failed:
        status_colour = "red"
    else:
        status_colour = "magenta"

    click.secho(
        "The package status is: %(status)s"
        % {"status": click.style(package_status, fg=status_colour)}
    )

    if reason:
        click.secho(
            "Reason given: %(reason)s" % {"reason": click.style(reason, fg="yellow")},
            fg=status_colour,
        )
