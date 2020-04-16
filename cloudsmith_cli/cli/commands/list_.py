# -*- coding: utf-8 -*-
"""CLI/Commands - List objects."""
from __future__ import absolute_import, print_function, unicode_literals

import functools
from operator import itemgetter

import click

from ...core.api.distros import list_distros
from ...core.api.packages import get_package_format_names_with_distros, list_packages
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from . import entitlements
from .main import main
from .repos import get as get_repos


@main.group(cls=command.AliasGroup, name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def list_(ctx, opts):  # pylint: disable=unused-argument
    """
    List distros, packages, repos and entitlements.

    See the help for subcommands for more information on each.
    """


@list_.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "package-format",
    default=None,
    required=False,
    type=click.Choice(get_package_format_names_with_distros()),
)
@click.pass_context
def distros(ctx, opts, package_format):
    """List available distributions."""
    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo("Getting list of distributions ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get list of distributions!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            distros_ = list_distros(package_format=package_format)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, distros_):
        return

    headers = ["Distro", "Release", "Format", "Distro / Release (Identifier)"]
    if package_format:
        headers.remove("Format")

    rows = []
    for distro in sorted(distros_, key=itemgetter("slug")):
        if not distro["versions"]:
            continue

        for release in sorted(distro["versions"], key=itemgetter("slug")):
            row = [
                click.style(distro["name"], fg="cyan"),
                click.style(release["name"], fg="yellow"),
                click.style(distro["format"], fg="blue"),
                "%(distro)s/%(release)s"
                % {
                    "distro": click.style(distro["slug"], fg="magenta"),
                    "release": click.style(release["slug"], fg="green"),
                },
            ]

            if package_format:
                row.pop(2)  # Remove format column

            rows.append(row)

    if distros_:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = sum(
        1 for distro in distros_ for release in distro["versions"] if release
    )
    list_suffix = "distribution release%s" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@list_.command(name="entitlements", aliases=["ents"])
@entitlements.list_entitlements_options
@functools.wraps(entitlements.list_entitlements)
@click.pass_context
def entitlements_(*args, **kwargs):  # noqa pylint: disable=missing-docstring
    return entitlements.list_entitlements(*args, **kwargs)


@list_.command(aliases=["pkgs"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_cli_list_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "-q",
    "--query",
    help=("A boolean-like search term for querying package attributes."),
)
@click.pass_context
def packages(ctx, opts, owner_repo, page, page_size, query):
    """
    List packages for a repository.

    OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
    REPO name to list packages for that namespace and repository. All separated
    by a slash.

    You can use the search query (-q|--query) to filter packages:

      - By name: 'my-package' (implicit) or 'name:my-package'

      - By filename: 'pkg.ext' (implicit) or 'filename:pkg.ext' (explicit)

      - By version: '1.0.0' (implicit) or 'version:1.0.0' (explicit)

      - By arch: 'x86_64' (implicit) or 'architecture:x86_64' (explicit)

      - By disto: 'el' (implicit) or 'distribution:el' (explicit)

    You can also modify the search terms:

      - '^foo' to anchor to start of term

      - 'foo$' to anchor to end of term

      - 'foo*bar' for fuzzy matching

      - '~foo' for negation of the term (explicit only, e.g. name:~foo)

    Multiple search terms are conjunctive (AND).

    Examples, to find packages named exactly foo, with a zip filename, that are
    NOT the x86 architecture, use something like this:

    --query 'name:^foo$ filename:.zip$ architecture:~x86'

    """
    owner, repo = owner_repo

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo("Getting list of packages ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get list of packages!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            packages_, page_info = list_packages(
                owner=owner, repo=repo, page=page, page_size=page_size, query=query
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, packages_, page_info):
        return

    headers = ["Name", "Version", "Status", "Owner / Repository (Identifier)"]
    rows = []
    for package in sorted(packages_, key=itemgetter("namespace", "slug")):
        rows.append(
            [
                click.style(_get_package_name(package), fg="cyan"),
                click.style(_get_package_version(package), fg="yellow"),
                click.style(_get_package_status(package), fg="blue"),
                "%(owner_slug)s/%(repo_slug)s/%(slug)s"
                % {
                    "owner_slug": click.style(package["namespace"], fg="magenta"),
                    "repo_slug": click.style(package["repository"], fg="magenta"),
                    "slug": click.style(package["slug"], fg="green"),
                },
            ]
        )

    if packages_:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(packages_)
    list_suffix = "package%s visible" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(
        num_results=num_results, page_info=page_info, suffix=list_suffix
    )


@list_.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_cli_list_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo",
    metavar="OWNER/REPO",
    callback=validators.validate_optional_owner_repo,
    default="",
    required=False,
)
@click.pass_context
def repos(ctx, opts, owner_repo, page, page_size):
    """
    List repositories for a namespace (owner).

    OWNER/REPO: Specify the OWNER namespace (i.e user or org) to list the
    repositories for that namespace.

    If REPO isn't specified, all repositories will be retrieved from the
    OWNER namespace.

    If OWNER isn't specified it'll default to the currently authenticated user
    (if any). If you're unauthenticated, no results will be returned.
    """
    ctx.forward(get_repos)


def _get_package_name(package):
    """Get the name (or filename) for a package."""
    return package["name"] or package["filename"]


def _get_package_status(package):
    """Get the status for a package."""
    status = package["status_str"] or "Unknown"
    stage = package["stage_str"] or "Unknown"
    if stage == "Fully Synchronised":
        return status
    return "%(status)s / %(stage)s" % {"status": status, "stage": stage}


def _get_package_version(package):
    """Get the version for a package (if any)."""
    return package["version"] or "None"
