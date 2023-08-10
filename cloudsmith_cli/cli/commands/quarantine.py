"""CLI/Commands - Quarantine."""

import functools

import click

from ...core.api import packages as api
from .. import command, decorators, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def common_quarantine_options(f):
    """Add common options for quarantine commands."""

    @decorators.common_cli_config_options
    @decorators.common_cli_list_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo_package",
        metavar="OWNER/REPO/PACKAGE",
        callback=validators.validate_owner_repo_package,
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


@main.group(cls=command.AliasGroup, aliases=["block"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def quarantine(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage quarantined packages in a repository.

    A quarantined package is not available for download from cloudsmith.
    This functionality is currently in Invitational Beta. Reach out through
    the chat function on the website to get it enabled for testing.

    See the help for subcommands for more information on each.
    """


def add_quarantine(ctx, opts, owner_repo_package, page, page_size):
    """
    Add a package to quarantine.

    A quarantined package is not available for download from cloudsmith.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE name (slug) of the
    package itself. All separated by a slash.

        Example: 'your-org/awesome-repo/bad-pkg'

    Full CLI example:

      $ cloudsmith qu add your-org/awesome-repo/bad-pkg
    """
    owner, repo, slug = owner_repo_package

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo(
        "Adding %(repository)s/%(package_slug)s to quarantine... "
        % {
            "repository": click.style(repo, bold=True),
            "package_slug": click.style(slug, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed quarantine!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api.quarantine_package(owner=owner, repo=repo, identifier=slug)

    click.secho("OK", fg="green", err=use_stderr)


@quarantine.command(name="add")
@common_quarantine_options
@functools.wraps(add_quarantine)
@click.pass_context
def add(*args, **kwargs):  # pylint: disable=missing-docstring
    return add_quarantine(*args, **kwargs)


def remove_quarantine(ctx, opts, owner_repo_package, page, page_size):
    """
    Remove a package from quarantine.

    A quarantined package is not available for download from cloudsmith.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE name (slug) of the
    package itself. All separated by a slash.

        Example: 'your-org/awesome-repo/checked-pkg'

    Full CLI example:

      $ cloudsmith qu rm your-org/awesome-repo/checked-pkg
    """
    owner, repo, slug = owner_repo_package

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo(
        "Removing %(repository)s/%(package_slug)s from quarantine... "
        % {
            "repository": click.style(repo, bold=True),
            "package_slug": click.style(slug, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed quarantine!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api.quarantine_restore_package(owner=owner, repo=repo, identifier=slug)

    click.secho("OK", fg="green", err=use_stderr)


@quarantine.command(name="remove", aliases=["rm", "restore"])
@common_quarantine_options
@functools.wraps(remove_quarantine)
@click.pass_context
def remove(*args, **kwargs):  # pylint: disable=missing-docstring
    return remove_quarantine(*args, **kwargs)
