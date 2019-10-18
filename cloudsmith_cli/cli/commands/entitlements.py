# -*- coding: utf-8 -*-
"""CLI/Commands - Push packages."""
from __future__ import absolute_import, print_function, unicode_literals

import functools
from operator import itemgetter

import click

from ...core.api import entitlements as api
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def validate_owner_repo_identifier(ctx, param, value):
    """Ensure that owner/repo/identifier is formatted correctly."""
    # pylint: disable=unused-argument
    form = "OWNER/REPO/IDENTIFIER"
    return validators.validate_slashes(param, value, minimum=3, maximum=3, form=form)


def common_entitlements_options(f):
    """Add common options for entitlement commands."""

    @click.option(
        "--show-tokens",
        default=False,
        is_flag=True,
        help="Show entitlement token string contents in output.",
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


@main.group(cls=command.AliasGroup, aliases=["ents"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def entitlements(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage the entitlements for a repository.

    See the help for subcommands for more information on each.
    """


def list_entitlements_options(f):
    """Options for list entitlements subcommand."""

    @common_entitlements_options
    @decorators.common_cli_config_options
    @decorators.common_cli_list_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
    )
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # pylint: disable=missing-docstring
        return ctx.invoke(f, *args, **kwargs)

    return wrapper


def list_entitlements(ctx, opts, owner_repo, page, page_size, show_tokens):
    """
    List entitlements for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the REPO
      name where you want to list entitlements for. All separated by a slash.

        Example: 'your-org/your-repo'

    Full CLI example:

      $ cloudsmith ents list your-org/your-repo
    """
    owner, repo = owner_repo

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.echo(
        "Getting list of entitlements for the %(repository)s "
        "repository ... " % {"repository": click.style(repo, bold=True)},
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to get list of entitlements!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            entitlements_, page_info = api.list_entitlements(
                owner=owner,
                repo=repo,
                page=page,
                page_size=page_size,
                show_tokens=show_tokens,
            )

    click.secho("OK", fg="green", err=use_stderr)

    print_entitlements(opts=opts, data=entitlements_, page_info=page_info)


@entitlements.command(name="list", aliases=["ls"])
@list_entitlements_options
@functools.wraps(list_entitlements)
@click.pass_context
def list_(*args, **kwargs):  # noqa pylint: disable=missing-docstring
    return list_entitlements(*args, **kwargs)


def print_entitlements(opts, data, page_info=None, show_list_info=True):
    """Print entitlements as a table or output in another format."""
    if utils.maybe_print_as_json(opts, data, page_info):
        return

    headers = ["Name", "Token", "Created / Updated", "Identifier"]

    rows = []
    for entitlement in sorted(data, key=itemgetter("name")):
        rows.append(
            [
                click.style(
                    "%(name)s (%(type)s)"
                    % {
                        "name": click.style(entitlement["name"], fg="cyan"),
                        "type": "user" if entitlement["user"] else "token",
                    }
                ),
                click.style(entitlement["token"], fg="yellow"),
                click.style(
                    entitlement["updated_at"] or entitlement["created_at"], fg="blue"
                ),
                click.style(entitlement["slug_perm"], fg="green"),
            ]
        )

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    if not show_list_info:
        return

    click.echo()

    num_results = len(data)
    list_suffix = "entitlement%s" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@entitlements.command(aliases=["new"])
@common_entitlements_options
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "--name",
    type=str,
    required=True,
    help="The name of the entitlement token (for informational purposes "
    'only). Must be something other than "Default".',
)
@click.option(
    "--token",
    type=str,
    required=False,
    help="The entitlement token value. Must be exactly 16 characters in "
    "length and only contain alphanumerics. If not specified then "
    "an entitlement token will be automatically generated.",
)
@click.pass_context
def create(ctx, opts, owner_repo, show_tokens, name, token):
    """
    Create a new entitlement in a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the REPO
      name where you want to create an entitlement. All separated by a slash.

        Example: 'your-org/your-repo'

    Full CLI example:

      $ cloudsmith ents create your-org/your-repo --name 'Foobar'
    """
    owner, repo = owner_repo

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.secho(
        "Creating %(name)s entitlement for the %(repository)s "
        "repository ... "
        % {
            "name": click.style(name, bold=True),
            "repository": click.style(repo, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to create the entitlement!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            entitlement = api.create_entitlement(
                owner=owner, repo=repo, name=name, token=token, show_tokens=show_tokens
            )

    click.secho("OK", fg="green", err=use_stderr)

    print_entitlements(opts=opts, data=[entitlement], show_list_info=False)


@entitlements.command(aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_identifier",
    metavar="OWNER/REPO/IDENTIFIER",
    callback=validate_owner_repo_identifier,
)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def delete(ctx, opts, owner_repo_identifier, yes):
    """
    Delete an entitlement from a repository.

    - OWNER/REPO/IDENTIFIER: Specify the OWNER namespace (i.e. user or org),
      and the REPO name that has an entitlement identified by IDENTIFIER. All
      separated by a slash.

        Example: 'your-org/your-repo/abcdef123456'

    Full CLI example:

      $ cloudsmith ents delete your-org/your-repo/abcdef123456
    """
    owner, repo, identifier = owner_repo_identifier

    delete_args = {
        "identifier": click.style(identifier, bold=True),
        "repository": click.style(repo, bold=True),
    }

    prompt = (
        "delete the %(identifier)s entitlement from the %(repository)s "
        "repository" % delete_args
    )
    if not utils.confirm_operation(prompt, assume_yes=yes):
        return

    click.secho(
        "Deleting %(identifier)s entitlement from the %(repository)s "
        "repository ... " % delete_args,
        nl=False,
    )

    context_msg = "Failed to delete the entitlement!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            api.delete_entitlement(owner=owner, repo=repo, identifier=identifier)

    click.secho("OK", fg="green")


@entitlements.command(aliases=["set"])
@common_entitlements_options
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_identifier",
    metavar="OWNER/REPO/IDENTIFIER",
    callback=validate_owner_repo_identifier,
)
@click.option(
    "--name",
    type=str,
    required=False,
    help="The name of the entitlement token (for informational purposes "
    'only). Must be something other than "Default".',
)
@click.option(
    "--token",
    type=str,
    required=False,
    help="The entitlement token value. Must be exactly 16 characters in "
    "length and only contain alphanumerics.",
)
@click.pass_context
def update(ctx, opts, owner_repo_identifier, show_tokens, name, token):
    """
    Update (set) a entitlement in a repository.

    - OWNER/REPO/IDENTIFIER: Specify the OWNER namespace (i.e. user or org),
      and the REPO name that has an entitlement identified by IDENTIFIER. All
      separated by a slash.

        Example: 'your-org/your-repo/abcdef123456'

    Full CLI example:

      $ cloudsmith ents update your-org/your-repo/abcdef123456 --name 'Newly'
    """
    owner, repo, identifier = owner_repo_identifier

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    click.secho(
        "Updating %(identifier)s entitlement for the %(repository)s "
        "repository ... "
        % {
            "identifier": click.style(identifier, bold=True),
            "repository": click.style(repo, bold=True),
        },
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to update the entitlement!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            entitlement = api.update_entitlement(
                owner=owner,
                repo=repo,
                identifier=identifier,
                name=name,
                token=token,
                show_tokens=show_tokens,
            )

    click.secho("OK", fg="green", err=use_stderr)

    print_entitlements(opts=opts, data=[entitlement], show_list_info=False)


@entitlements.command()
@common_entitlements_options
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_identifier",
    metavar="OWNER/REPO/IDENTIFIER",
    callback=validate_owner_repo_identifier,
)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def refresh(ctx, opts, owner_repo_identifier, show_tokens, yes):
    """
    Refresh an entitlement in a repository.

    Note that this changes the token associated with the entitlement.

    - OWNER/REPO/IDENTIFIER: Specify the OWNER namespace (i.e. user or org),
      and the REPO name that has an entitlement identified by IDENTIFIER. All
      separated by a slash.

        Example: 'your-org/your-repo/abcdef123456'

    Full CLI example:

      $ cloudsmith ents refresh your-org/your-repo/abcdef123456
    """
    owner, repo, identifier = owner_repo_identifier

    refresh_args = {
        "identifier": click.style(identifier, bold=True),
        "repository": click.style(repo, bold=True),
    }

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    prompt = (
        "refresh the %(identifier)s entitlement for the %(repository)s "
        "repository" % refresh_args
    )
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    click.secho(
        "Refreshing %(identifier)s entitlement for the %(repository)s "
        "repository ... " % refresh_args,
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to refresh the entitlement!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            entitlement = api.refresh_entitlement(
                owner=owner, repo=repo, identifier=identifier, show_tokens=show_tokens
            )

    click.secho("OK", fg="green", err=use_stderr)

    print_entitlements(opts=opts, data=[entitlement], show_list_info=False)


@entitlements.command()
@common_entitlements_options
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.argument("source", metavar="SOURCE", default=str)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def sync(ctx, opts, owner_repo, show_tokens, source, yes):
    """
    Sync entitlements from another repository.

    ***WARNING*** This will DELETE ALL of the existing entitlements in the
    repository and replace them with entitlements from the source repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the REPO
      name where you want to sync entitlements to. All separated by a slash.

        Example: 'your-org/your-repo'

    - SOURCE: Specify the SOURCE repository to copy the entitlements from.
      This *must* be in the same namespace as the destination repository.

        Example: 'source-repo'

    Full CLI example:

      $ cloudsmith ents sync your-org/your-repo source-repo
    """
    owner, repo = owner_repo

    sync_args = {
        "source": click.style(source, bold=True),
        "dest": click.style(repo, bold=True),
        "warning": click.style("*** WARNING ***", fg="yellow"),
    }

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    if not yes:
        click.secho(
            "%(warning)s This will DELETE ALL of the existing entitlements "
            "in the %(dest)s repository and replace them with entitlements "
            "from the %(source)s repository." % sync_args,
            fg="yellow",
            err=use_stderr,
        )
        click.echo()

    prompt = (
        "sync entitlements from the %(source)s repository to the "
        "%(dest)s repository" % sync_args
    )
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    click.secho(
        "Syncing entitlements from the %(source)s repository to the "
        "%(dest)s repository" % sync_args,
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to sync the entitlements!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            entitlements_, page_info = api.sync_entitlements(
                owner=owner, repo=repo, source=source, show_tokens=show_tokens
            )

    click.secho("OK", fg="green", err=use_stderr)

    print_entitlements(opts=opts, data=entitlements_, page_info=page_info)
