# -*- coding: utf-8 -*-
"""CLI/Commands - Delete packages."""
from __future__ import absolute_import, print_function, unicode_literals

import click

from ...core.api.packages import delete_package
from .. import decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.command(aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
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

    delete_args = {
        "owner": click.style(owner, bold=True),
        "repo": click.style(repo, bold=True),
        "package": click.style(slug, bold=True),
    }

    prompt = "delete the %(package)s from %(owner)s/%(repo)s" % delete_args
    if not utils.confirm_operation(prompt, assume_yes=yes):
        return

    click.echo(
        "Deleting %(package)s from %(owner)s/%(repo)s ... " % delete_args, nl=False
    )

    context_msg = "Failed to delete the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            delete_package(owner=owner, repo=repo, identifier=slug)

    click.secho("OK", fg="green")
