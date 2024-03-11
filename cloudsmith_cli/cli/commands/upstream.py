"""CLI/Commands - create, retrieve, update or delete repository upstreams."""

import json

import click

from ...core.api import upstreams as api
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import (
    fmt_bool,
    fmt_datetime,
    maybe_spinner,
    maybe_truncate_list,
    maybe_truncate_string,
)
from .main import main

UPSTREAM_FORMATS = [
    "dart",
    "deb",
    "docker",
    "helm",
    "maven",
    "nuget",
    "npm",
    "python",
    "rpm",
    "ruby",
    "cran",
]


def print_upstreams(upstreams, upstream_fmt):
    """Print upstreams as a table or output in another format."""

    def build_row(u):
        row = [
            click.style(u["name"], fg="cyan"),
            click.style(maybe_truncate_string(u["upstream_url"]), fg="cyan"),
            click.style(str(u["auth_mode"]), fg="yellow"),
            click.style(
                maybe_truncate_string(str(u["auth_secret"] or "")),
                fg="yellow",
            ),
            click.style(str(u["auth_username"] or ""), fg="yellow"),
            click.style(fmt_datetime(u["created_at"]), fg="blue"),
            click.style(str(u["extra_header_1"] or ""), fg="yellow"),
            click.style(str(u["extra_header_2"] or ""), fg="yellow"),
            click.style(str(u["extra_value_1"] or ""), fg="yellow"),
            click.style(str(u["extra_value_2"] or ""), fg="yellow"),
            click.style(fmt_bool(u["is_active"]), fg="green"),
            click.style(u["mode"], fg="green"),
            click.style(str(u["priority"]), fg="green"),
            click.style(u["slug_perm"], fg="green"),
            click.style(fmt_datetime(u["updated_at"]), fg="blue"),
            click.style(fmt_bool(u["verify_ssl"]), fg="green"),
        ]

        if upstream_fmt == "deb":
            # `Component`, `Distribution Versions` and `Upstream Distribution` are deb-only
            row.append(click.style(str(u.get("component", None)), fg="yellow"))
            row.append(
                click.style(
                    str(maybe_truncate_list(u.get("distro_versions", []))),
                    fg="yellow",
                )
            )
            row.append(
                click.style(str(u.get("upstream_distribution", None)), fg="yellow")
            )

        if upstream_fmt == "rpm":
            # `Distribution Version` is rpm-only
            row.append(click.style(str(u.get("distro_version", "")), fg="yellow"))

        return row

    headers = [
        "Name",
        "Upstream Url",
        "Auth mode",
        "Auth Secret",
        "Auth Username",
        "Created At",
        "Extra Header 1",
        "Extra Header 2",
        "Extra Value 1",
        "Extra Value 2",
        "Active",
        "Mode",
        "Priority",
        "Slug Perm",
        "Updated At",
        "Verify SSL",
    ]

    if upstream_fmt == "deb":
        headers.append("Component")
        headers.append("Distribution Versions")
        headers.append("Upstream Distribution")

    if upstream_fmt == "rpm":
        headers.append("Distribution Version")

    rows = [build_row(x) for x in upstreams]

    click.echo()
    utils.pretty_print_table(headers, rows)
    click.echo()

    num_results = len(rows)
    list_suffix = "upstream%s" % ("" if num_results == 1 else "s")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@main.group(cls=command.AliasGroup, name="upstream", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def upstream(*args, **kwargs):
    """
    Manage upstreams for a repository.

    See the help for subcommands for more information on each.
    """


def build_upstream_group_func(upstream_fmt):
    @decorators.common_cli_config_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.pass_context
    def func(ctx, opts):
        pass

    func.__doc__ = (
        """
        Manage %s upstreams for a repository.

        See the help for subcommands for more information on each.
        """
        % upstream_fmt
    )
    return func


def build_upstream_list_command(upstream_fmt):
    @decorators.common_cli_config_options
    @decorators.common_cli_list_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
    )
    @click.pass_context
    def func(ctx, opts, owner_repo, page, page_size):
        owner, repo = owner_repo

        # Use stderr for messages if the output is something else (e.g.  # JSON)
        use_stderr = opts.output != "pretty"

        click.echo("Getting upstreams... ", nl=False, err=use_stderr)

        context_msg = "Failed to get upstreams!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                upstreams, page_info = api.list_upstreams(
                    owner=owner,
                    repo=repo,
                    upstream_format=upstream_fmt,
                    page=page,
                    page_size=page_size,
                )

        click.secho("OK", fg="green", err=use_stderr)

        if utils.maybe_print_as_json(opts, upstreams, page_info):
            return

        print_upstreams(upstreams, upstream_fmt)

    func.__doc__ = f"""
        List {upstream_fmt} upstreams for a repository.

        This requires appropriate permissions for the owner (a member of the organisation, repository privileges and a valid API key).

        - OWNER/REPO: Specify the OWNER namespace (organization) and REPO (repository) to target a specific Cloudsmith repository.

          Example: 'your-org/your-repo'

        Full CLI example:

          $ cloudsmith upstream {upstream_fmt} ls your-org/your-repo
        """
    return func


def build_upstream_create_command(upstream_fmt):
    @decorators.common_cli_config_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
    )
    @click.argument("upstream_config_file", type=click.File("rb"), required=True)
    @click.pass_context
    def func(ctx, opts, owner_repo, upstream_config_file):
        # Use stderr for messages if the output is something else (e.g. JSON)
        use_stderr = opts.output != "pretty"

        owner, repo = owner_repo

        upstream_config = json.load(upstream_config_file)

        upstream_name = upstream_config.get("name", None)

        if upstream_name is None:
            raise click.BadParameter(
                "Name is a required field for creating an upstream.", param="name"
            )

        click.secho(
            'Creating "%(name)s" upstream for the %(owner)s/%(repo)s repository...'
            % {
                "name": click.style(upstream_name, bold=True),
                "owner": click.style(owner, bold=True),
                "repo": click.style(repo, bold=True),
            },
            nl=False,
            err=use_stderr,
        )

        context_msg = "Failed to create the upstream!"

        with handle_api_exceptions(ctx, opts, context_msg=context_msg):
            with maybe_spinner(opts):
                upstream_resp_data = api.create_upstream(
                    owner, repo, upstream_fmt, upstream_config
                )

        click.secho("OK", fg="green", err=use_stderr)

        if utils.maybe_print_as_json(opts, upstream_resp_data):
            return

        print_upstreams([upstream_resp_data], upstream_fmt)

    func.__doc__ = f"""
        Create a {upstream_fmt} upstream for a repository.

        This requires appropriate permissions for the owner (a member of the organisation, repository privileges and a valid API key).

        - OWNER/REPO: Specify the OWNER namespace (organization) and REPO (repository) to target a specific Cloudsmith repository.

          Example: 'your-org/your-repo'

        - UPSTREAM_CONFIG_FILE: Config json file specifying the settings for the upstream to be updated.

          For a full list of supported config properties, please refer to the "body params" section of the api reference for the relevant endpoint at:

          https://help.cloudsmith.io/reference/repos_upstream_{upstream_fmt}_create

          \b
          Example:
            {{
              "name": "Some Upstream",
              "upstream_url": "https://someupstream.net",
              "mode": "Proxy Only",
              "auth_mode": "None",
              "priority": 5,
              ...
            }}

        Full CLI example:

          $ cloudsmith upstream {upstream_fmt} create your-org/your-repo ./path/to/upstream-config.json
        """

    return func


def build_upstream_update_command(upstream_fmt):
    @decorators.common_cli_config_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo_slug_perm",
        metavar="OWNER/REPO/SLUG_PERM",
        callback=validators.validate_owner_repo_slug_perm,
    )
    @click.argument("upstream_config_file", type=click.File("rb"), required=True)
    @click.pass_context
    def func(ctx, opts, owner_repo_slug_perm, upstream_config_file):
        # Use stderr for message if the output is something else (e.g. JSON)
        use_stderr = opts.output != "pretty"

        owner, repo, slug_perm = owner_repo_slug_perm

        upstream_config = json.load(upstream_config_file)

        click.secho(
            "Updating the %(slug_perm)s upstream from the %(owner)s/%(repo)s repository ... "
            % {
                "owner": click.style(owner, bold=True),
                "repo": click.style(repo, bold=True),
                "slug_perm": click.style(slug_perm, bold=True),
            },
            nl=False,
            err=use_stderr,
        )

        context_msg = "Failed to update the upstream!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                upstream_resp_data = api.update_upstream(
                    owner, repo, slug_perm, upstream_fmt, upstream_config
                )

        click.secho("OK", fg="green", err=use_stderr)

        if utils.maybe_print_as_json(opts, upstream_resp_data):
            return

        print_upstreams([upstream_resp_data], upstream_fmt)

    func.__doc__ = f"""
        Update a {upstream_fmt} upstream for a repository.

        This requires appropriate permissions for the owner (a member of the organisation, repository privileges and a valid API key).

        - OWNER/REPO/SLUG_PERM: Specify the OWNER namespace (organization), REPO (repository) and SLUG_PERM (upstream) to target a specific upstream belonging to a repo.

          Example: 'your-org/your-repo/abcdefg'

        - UPSTREAM_CONFIG_FILE: Config json file specifying the settings for the upstream to be updated.

          For a full list of supported config properties, please refer to the "body params" section of the api reference for the relevant endpoint at:

          https://help.cloudsmith.io/reference/repos_upstream_{upstream_fmt}_partial_update

          \b
          Example:
            {{
              "name": "Some Upstream",
              "upstream_url": "https://someupstream.net",
              "mode": "Proxy Only",
              "auth_mode": "None",
              "priority": 5,
              ...
            }}

        Full CLI example:

          $ cloudsmith upstream {upstream_fmt} update your-org/your-repo/abcdefg ./path/to/upstream-config.json
        """

    return func


def build_upstream_delete_command(upstream_fmt):
    @decorators.common_cli_config_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.argument(
        "owner_repo_slug_perm",
        metavar="OWNER/REPO/SLUG_PERM",
        callback=validators.validate_owner_repo_slug_perm,
    )
    @click.option(
        "-y",
        "--yes",
        default=False,
        is_flag=True,
        help="Assume yes as default answer to questions (this is dangerous!)",
    )
    @click.pass_context
    def func(ctx, opts, owner_repo_slug_perm, yes):
        # Use stderr for message if the output is something else (e.g. JSON)
        use_stderr = opts.output != "pretty"

        owner, repo, slug_perm = owner_repo_slug_perm

        delete_args = {
            "owner": click.style(owner, bold=True),
            "repo": click.style(repo, bold=True),
            "slug_perm": click.style(slug_perm, bold=True),
        }

        prompt = (
            "delete the %(slug_perm)s upstream from the %(owner)s/%(repo)s repository"
            % delete_args
        )
        if not utils.confirm_operation(prompt, assume_yes=yes):
            return

        click.secho(
            "Deleting the %(slug_perm)s upstream from the %(owner)s/%(repo)s repository ... "
            % delete_args,
            nl=False,
            err=use_stderr,
        )

        context_msg = "Failed to delete the upstream!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                api.delete_upstream(owner, repo, upstream_fmt, slug_perm)

        click.secho("OK", fg="green", err=use_stderr)

    func.__doc__ = f"""
        Delete a {upstream_fmt} upstream for a repository.

        This requires appropriate permissions for the owner (a member of the organisation, repository privileges and a valid API key).

        - OWNER/REPO/SLUG_PERM: Specify the OWNER namespace (organization), REPO (repository) and SLUG_PERM (upstream) to target a specific upstream belonging to a repo.

          Example: 'your-org/your-repo/abcdefg'

        Full CLI example:

          $ cloudsmith upstream {upstream_fmt} delete your-org/your-repo/abcdefg
        """

    return func


for upstream_format in UPSTREAM_FORMATS:
    # Build a click group for the upstream name e.g. dart, npm, ruby.
    # Add it to the "upstream" parent group.
    # This gives us e.g. `cloudsmith upstream dart` in the cli.
    upstream_group = upstream.group(
        cls=command.AliasGroup, name=upstream_format, aliases=[]
    )(build_upstream_group_func(upstream_format))

    # Add create/list/update/delete commands to the child group we created above.
    # This gives us e.g. `cloudsmith upstream dart ls`.
    upstream_group.command(name="list", aliases=["ls"])(
        build_upstream_list_command(upstream_format)
    )
    upstream_group.command(name="create", aliases=["new"])(
        build_upstream_create_command(upstream_format)
    )
    upstream_group.command(name="delete", aliases=["rm"])(
        build_upstream_delete_command(upstream_format)
    )
    upstream_group.command(name="update")(
        build_upstream_update_command(upstream_format)
    )
