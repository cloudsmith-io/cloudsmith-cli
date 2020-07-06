# -*- coding: utf-8 -*-
"""CLI/Commands - List objects."""
from __future__ import absolute_import, print_function, unicode_literals

from operator import itemgetter

import click

from ...core.api.packages import (
    get_package_tags as api_get_package_tags,
    tag_package as api_tag_package,
)
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def _parse_tags(tags):
    """Parse tags from CSV into a list."""
    return [x.strip() for x in (tags or "").split(",")]


def _print_tags(opts, all_tags, all_immutable_tags):
    """Print the tags for a package."""
    all_combined_tags = {"tags": all_tags, "tags_immutable": all_immutable_tags}

    if utils.maybe_print_as_json(opts, all_combined_tags):
        return

    headers = ["Tag", "Type", "Immutable"]

    rows = []
    for tag_type, tags in sorted(all_tags.items(), key=itemgetter(0)):
        immutable_tags = all_immutable_tags.get(tag_type) or []
        for tag in sorted(tags):
            immutable = "Yes" if tag in immutable_tags else "No"
            rows.append(
                [
                    click.style(tag, fg="cyan"),
                    click.style(tag_type, fg="yellow"),
                    click.style(immutable, fg="magenta"),
                ]
            )

    if all_tags:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(rows)
    list_suffix = "tag%s" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@main.group(name="tags", cls=command.AliasGroup, aliases=["tag"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def tags_(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage the tags for a package in a repository.

    See the help for subcommands for more information on each.
    """


@tags_.command(name="list", aliases=["ls"])
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
def list_tags(ctx, opts, owner_repo_package):
    """
    List tags for a package in a repository.

    This requires appropriate (read) permissions for the package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE identifier of the
    package itself. All separated by a slash.

      Example: 'your-org/awesome-repo/better-pkg'.

    Full CLI example:

      $ cloudsmith tags list your-org/awesome-repo/better-pkg
    """
    owner, repo, package = owner_repo_package

    click.echo(
        "Listing tags for the '%(package)s' package ... "
        % {"package": click.style(package, bold=True)},
        nl=False,
    )

    context_msg = "Failed to list tags for the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package_tags, package_tags_immutable = api_get_package_tags(
                owner=owner, repo=repo, identifier=package
            )

    click.secho("OK", fg="green")

    _print_tags(opts, package_tags, package_tags_immutable)


@tags_.command(name="add")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("tags", metavar="TAGS")
@click.option(
    "--immutable",
    default=False,
    is_flag=True,
    help=(
        "If true, the tags created will be immutable (cannot be changed). In "
        "practice, this means the tags cannot be (easily) deleted. A repository "
        "admin can explicitly remove immutable tags."
    ),
)
@click.pass_context
def add_tags(ctx, opts, owner_repo_package, tags, immutable):
    """
    Add tags to a package in a repository.

    This requires appropriate (write) permissions for the package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE identifier of the
    package itself. All separated by a slash.

      Example: 'your-org/awesome-repo/better-pkg'.

    - TAGS: A comma-separated value list of the tags you want to add.

      Example: foo,bar

    Full CLI example:

      $ cloudsmith tags add your-org/awesome-repo/better-pkg foo,bar
    """
    owner, repo, package = owner_repo_package
    tags = _parse_tags(tags)

    click.echo(
        "Adding '%(tags)s' tag%(s)s to the '%(package)s' package ... "
        % {
            "package": click.style(package, bold=True),
            "tags": click.style(", ".join(tags or [])),
            "s": "s" if len(tags) != 1 else "",
        },
        nl=False,
    )

    context_msg = "Failed to add tags to package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package_tags, package_tags_immutable = api_tag_package(
                owner=owner,
                repo=repo,
                identifier=package,
                data={"action": "add", "tags": tags, "is_immutable": immutable},
            )

    click.secho("OK", fg="green")

    _print_tags(opts, package_tags, package_tags_immutable)


@tags_.command(name="clear")
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
def clear_tags(ctx, opts, owner_repo_package):
    """
    Clear all existing (non-immutable) tags from a package in a repository.

    This requires appropriate (write) permissions for the package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE identifier of the
    package itself. All separated by a slash.

      Example: 'your-org/awesome-repo/better-pkg'.

    Full CLI example:

      $ cloudsmith tags clear your-org/awesome-repo/better-pkg
    """
    owner, repo, package = owner_repo_package

    click.echo(
        "Clearing tags on the '%(package)s' package ... "
        % {"package": click.style(package, bold=True)},
        nl=False,
    )

    context_msg = "Failed to clear tags on package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package_tags, package_tags_immutable = api_tag_package(
                owner=owner, repo=repo, identifier=package, data={"action": "clear"}
            )

    click.secho("OK", fg="green")

    _print_tags(opts, package_tags, package_tags_immutable)


@tags_.command(name="remove", aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("tags", metavar="TAGS")
@click.pass_context
def remove_tags(ctx, opts, owner_repo_package, tags):
    """
    Remove tags from a package in a repository.

    This requires appropriate (write) permissions for the package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE identifier of the
    package itself. All separated by a slash.

      Example: 'your-org/awesome-repo/better-pkg'.

    - TAGS: A comma-separated value list of the tags you want to remove.

      Example: foo,bar

    Full CLI example:

      $ cloudsmith tags remove your-org/awesome-repo/better-pkg foo,bar
    """
    owner, repo, package = owner_repo_package
    tags = _parse_tags(tags)

    click.echo(
        "Removing '%(tags)s' tag%(s)s to the '%(package)s' package ... "
        % {
            "package": click.style(package, bold=True),
            "tags": click.style(", ".join(tags or [])),
            "s": "s" if len(tags) != 1 else "",
        },
        nl=False,
    )

    context_msg = "Failed to remove tags from package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package_tags, package_tags_immutable = api_tag_package(
                owner=owner,
                repo=repo,
                identifier=package,
                data={"action": "remove", "tags": tags},
            )

    click.secho("OK", fg="green")

    _print_tags(opts, package_tags, package_tags_immutable)


@tags_.command(name="replace")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("tags", metavar="TAGS")
@click.option(
    "--immutable",
    default=False,
    is_flag=True,
    help=(
        "If true, the tags created will be immutable (cannot be changed). In "
        "practice, this means the tags cannot be (easily) deleted. A repository "
        "admin can explicitly remove immutable tags."
    ),
)
@click.pass_context
def replace_tags(ctx, opts, owner_repo_package, tags, immutable):
    """
    Replace all existing (non-immutable) tags on a package in a repository.

    This requires appropriate (write) permissions for the package.

    - OWNER/REPO/PACKAGE: Specify the OWNER namespace (i.e. user or org), the
    REPO name where the package is stored, and the PACKAGE identifier of the
    package itself. All separated by a slash.

      Example: 'your-org/awesome-repo/better-pkg'.

    - TAGS: A comma-separated value list of the tags you want to replace existing with.

      Example: foo,bar

    Full CLI example:

      $ cloudsmith tags replace your-org/awesome-repo/better-pkg foo,bar
    """
    owner, repo, package = owner_repo_package
    tags = _parse_tags(tags)

    click.echo(
        "Replacing existing with '%(tags)s' tag%(s)s on the '%(package)s' package ... "
        % {
            "package": click.style(package, bold=True),
            "tags": click.style(", ".join(tags or [])),
            "s": "s" if len(tags) != 1 else "",
        },
        nl=False,
    )

    context_msg = "Failed to replace tags on package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package_tags, package_tags_immutable = api_tag_package(
                owner=owner,
                repo=repo,
                identifier=package,
                data={"action": "replace", "tags": tags, "is_immutable": immutable},
            )

    click.secho("OK", fg="green")

    _print_tags(opts, package_tags, package_tags_immutable)
