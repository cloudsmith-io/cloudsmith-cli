# -*- coding: utf8 -*-
"""CLI/Commands - create, retrieve, update or delete repositories."""
from __future__ import absolute_import, print_function, unicode_literals

import json
from operator import itemgetter

import click
import six

from ...core.api import repos as api
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def print_repositories(opts, data, page_info=None, show_list_info=True):
    """Print repositories as a table or output in another format."""
    headers = [
        "Name",
        "Type",
        "Packages",
        "Groups",
        "Downloads",
        "Size",
        "Owner / Repository (Identifier)",
    ]

    rows = []
    for repo in sorted(data, key=itemgetter("namespace", "slug")):
        rows.append(
            [
                click.style(repo["name"], fg="cyan"),
                click.style(repo["repository_type_str"], fg="yellow"),
                click.style(six.text_type(repo["package_count"]), fg="blue"),
                click.style(six.text_type(repo["package_group_count"]), fg="blue"),
                click.style(six.text_type(repo["num_downloads"]), fg="blue"),
                click.style(six.text_type(repo["size_str"]), fg="blue"),
                "%(owner_slug)s/%(slug)s"
                % {
                    "owner_slug": click.style(repo["namespace"], fg="magenta"),
                    "slug": click.style(repo["slug"], fg="green"),
                },
            ]
        )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(data)
    list_suffix = "repositor%s visible" % ("ies" if num_results != 1 else "y")
    utils.pretty_print_list_info(
        num_results=num_results, page_info=page_info, suffix=list_suffix
    )


@main.group(cls=command.AliasGroup, name="repositories", aliases=["repos"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def repositories(ctx, opts):  # pylink: disable=unused-argument
    """
    Manage Repositories.

    See the help for subommands for more information on each.
    """


@repositories.command(name="get", aliases=["list", "ls"])
@decorators.common_cli_config_options
@decorators.common_cli_list_options
@decorators.common_cli_output_options
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
def get(ctx, opts, owner_repo, page, page_size):
    """
    List repositories for a namespace (owner).

    OWNER/REPO: Specify the OWNER namespace (i.e user or org) to list the
    repositories for that namespace.

    If REPO isn't specified, all repositories will be retrieved from the
    OWNER namespace.

    If OWNER isn't specified it'll default to the currently authenticated user
    (if any). If you're unauthenticated, no results will be returned.
    """
    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo("Getting list of repositories ... ", nl=False, err=use_stderr)

    if isinstance(owner_repo, list):
        if len(owner_repo) == 1:
            owner = owner_repo[0]
            repo = None
        else:
            owner, repo = owner_repo
    if isinstance(owner_repo, str):
        repo = None

        if owner_repo:
            owner = owner_repo
        else:
            owner = None

    context_msg = "Failed to get list of repositories!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            repos_, page_info = api.list_repos(
                owner=owner, repo=repo, page=page, page_size=page_size
            )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, repos_, page_info):
        return

    print_repositories(opts=opts, data=repos_, show_list_info=False)


@repositories.command(aliases=["new"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument("owner", default=None, required=True)
@click.argument("repo_config_file", type=click.File("rb"), required=True)
@click.pass_context
def create(ctx, opts, owner, repo_config_file):
    """
    Create a new repository in a namespace.

    - OWNER: Specify the OWNER namespace (i.e. user or org) where you want
      to create a repository.

        Example: 'your-org'

    - REPO_CONFIG_FILE: Config file specifying the settings for the
      repository to be created.

        \b
        Example:
        {
          "name": "your-repo",
          "description": "your repo description",
          "repository_type_str": "Private",
          "slug": "your-repo-slug"
        }

    Full CLI example:

      $ cloudsmith repos create your-org repo-config-file.json
    """
    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = opts.output != "pretty"
    repo_config = json.load(repo_config_file)

    repo_name = repo_config.get("name", None)
    if repo_name is None:
        raise click.BadParameter(
            "Name is a required field for creating a repository.", param="name"
        )

    click.secho(
        "Creating %(name)s repository for the %(owner)s namespace ..."
        % {
            "name": click.style(repo_name, bold=True),
            "owner": click.style(owner, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to create the repository!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            repository = api.create_repo(owner, repo_config)

    click.secho("OK", fg="green", err=use_stderr)

    print_repositories(opts=opts, data=[repository], show_list_info=False)


@repositories.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.argument("repo_config_file", type=click.File("rb"), required=True)
@click.pass_context
def update(ctx, opts, owner_repo, repo_config_file):
    """
    Update a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org),
      and the REPO name to be updated. All separated by a slash.

        Example: 'your-org/your-repo'

    - REPO_CONFIG_FILE: Config file specifying the settings to
      update on the repository.

        \b
        Example:
        {
          "description": "your updated repo description",
          "repository_type_str": "Open-Source",
        }

    Full CLI example:

      $ cloudsmith repos update your-org/your-repo repo-config-file.json

    """
    # Use stderr for message if the output is something else (e.g. JSON)
    use_stderr = opts.output != "pretty"

    owner, repo = owner_repo
    repo_config = json.load(repo_config_file)

    click.secho(
        "Updating %(name)s repository in the %(owner)s namespace ..."
        % {
            "name": click.style(repo, bold=True),
            "owner": click.style(owner, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to update the repository!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            repository = api.update_repo(owner, repo, repo_config)

    click.secho("OK", fg="green", err=use_stderr)

    print_repositories(opts=opts, data=[repository], show_list_info=False)


@repositories.command(aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def delete(ctx, opts, owner_repo, yes):
    """
    Delete a repository from a namespace.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the name of the REPO
      to be deleted, separated by a slash.

        Example: 'your-org/your-repo'

    Full CLI example:

      $ cloudsmith repos delete your-org/your-repo
    """
    owner, repo = owner_repo
    delete_args = {
        "namespace": click.style(owner, bold=True),
        "repository": click.style(repo, bold=True),
    }

    prompt = "delete the %(repository)s from the %(namespace)s namespace" % delete_args
    if not utils.confirm_operation(prompt, assume_yes=yes):
        return

    click.secho(
        "Deleting %(repository)s from the %(namespace)s namespace ... " % delete_args,
        nl=False,
    )

    context_msg = "Failed to delete the repository!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api.delete_repo(owner=owner, repo=repo)

    click.secho("OK", fg="green")
