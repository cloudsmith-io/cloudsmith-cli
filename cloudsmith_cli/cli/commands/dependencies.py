"""CLI/Commands - Dependencies."""

import functools

import click

from ...core.api.packages import get_package_dependencies
from .. import decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def list_dependencies_options(f):
    """Options for list dependencies subcommand."""

    @decorators.common_cli_config_options
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


def list_dependencies(ctx, opts, owner_repo_package):
    """
    List direct (non-transitive) dependencies for a package.

    NOTE: These are not guaranteed to be complete, and only represent the *direct* /
    *non-transitive* dependencies of a package. If packages consistently show
    no dependencies then it is possible that dependency extraction isn't support
    for the package format yet.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE name (identifier) of the
    package itself. All separated by a slash.

    Example: 'your-org/awesome-repo/better-pkg'.
    """
    owner, repo, identifier = owner_repo_package

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo(
        "Getting direct (non-transitive) dependencies of %(package)s in "
        "%(owner)s/%(repo)s ... "
        % {
            "owner": click.style(owner, bold=True),
            "repo": click.style(repo, bold=True),
            "package": click.style(identifier, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to get dependencies of package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            deps, page_info = get_package_dependencies(
                owner=owner, repo=repo, identifier=identifier
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, deps, page_info):
        return

    headers = ["Type", "Name", "Operator", "Version"]
    rows = []
    for dep in deps:
        rows.append(
            [
                click.style(dep["dep_type"], fg="cyan"),
                click.style(dep["name"], fg="yellow"),
                click.style(dep["operator"], fg="magenta"),
                click.style(dep["version"] or "", fg="green"),
            ]
        )

    if deps:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()
    num_results = len(deps)
    list_suffix = "direct dependenc%s" % ("ies" if num_results != 1 else "y")
    utils.pretty_print_list_info(
        num_results=num_results, page_info=page_info, suffix=list_suffix
    )


@main.command(name="dependencies", aliases=["deps"])
@list_dependencies_options
@functools.wraps(list_dependencies)
@click.pass_context
def dependencies_(*args, **kwargs):
    return list_dependencies(*args, **kwargs)
