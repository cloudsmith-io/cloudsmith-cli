"""CLI/Commands - create, retrieve, update or delete repositories."""

import json
from operator import itemgetter

import click

from ...core.api import repos as api
from ...core.pagination import paginate_results
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


def print_repositories(opts, data, page_info=None, show_list_info=True, page_all=False):
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

    rows = [
        [
            click.style(repo["name"], fg="cyan"),
            click.style(repo["repository_type_str"], fg="yellow"),
            click.style(str(repo["package_count"]), fg="blue"),
            click.style(str(repo["package_group_count"]), fg="blue"),
            click.style(str(repo["num_downloads"]), fg="blue"),
            click.style(str(repo["size_str"]), fg="blue"),
            "{owner_slug}/{slug}".format(
                owner_slug=click.style(repo["namespace"], fg="magenta"),
                slug=click.style(repo["slug"], fg="green"),
            ),
        ]
        for repo in sorted(data, key=itemgetter("namespace", "slug"))
    ]

    if data:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    if not show_list_info:
        return

    num_results = len(data)
    list_suffix = "repositor%s" % ("ies" if num_results != 1 else "y")
    utils.pretty_print_list_info(
        num_results=num_results,
        page_info=None if page_all else page_info,
        suffix=f"{list_suffix} retrieved" if page_all else f"{list_suffix} visible",
        page_all=page_all,
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
def get(ctx, opts, owner_repo, page, page_size, page_all):
    """
    List repositories for a namespace (owner).

    OWNER/REPO: Specify the OWNER namespace (i.e user or org) to list the
    repositories for that namespace.

    If REPO isn't specified, all repositories will be retrieved from the
    OWNER namespace.

    If OWNER isn't specified it'll default to the currently authenticated user
    (if any). If you're unauthenticated, no results will be returned.
    """
    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)

    if isinstance(owner_repo, list):
        if len(owner_repo) == 1:
            owner = owner_repo[0]
            repo = None
        else:
            owner, repo = owner_repo
    elif isinstance(owner_repo, str):
        repo = None
        owner = owner_repo or None
    else:
        owner = None
        repo = None

    if page_all and repo:
        raise click.UsageError(
            "The --page-all option cannot be used when specifying a single repository (OWNER/REPO). Omit the repository slug or remove --page-all."
        )

    click.echo("Getting list of repositories ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get list of repositories!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        repos_, page_info = paginate_results(
            api.list_repos, page_all, page, page_size, owner=owner, repo=repo
        )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, repos_, page_info):
        return

    print_repositories(
        opts=opts,
        data=repos_,
        show_list_info=True,
        page_info=page_info,
        page_all=page_all,
    )


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
    use_stderr = utils.should_use_stderr(opts)
    repo_config = json.load(repo_config_file)

    repo_name = repo_config.get("name", None)
    if repo_name is None:
        raise click.BadParameter(
            "Name is a required field for creating a repository.", param="name"
        )

    click.secho(
        f"Creating {click.style(repo_name, bold=True)} repository for the {click.style(owner, bold=True)} namespace ...",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to create the repository!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        repository = api.create_repo(owner, repo_config)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, [repository]):
        return

    print_repositories(opts=opts, data=[repository], show_list_info=True)


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
        f"Updating {click.style(repo, bold=True)} repository in the {click.style(owner, bold=True)} namespace ...",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to update the repository!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        repository = api.update_repo(owner, repo, repo_config)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, [repository]):
        return

    print_repositories(opts=opts, data=[repository], show_list_info=True)


def print_gpg_key(gpg_key):
    """Print a repository's GPG key details as human-readable text."""
    click.echo()
    click.echo(
        f"Fingerprint: {click.style(gpg_key.get('fingerprint') or '(none)', fg='green')}"
    )
    click.echo(
        "Fingerprint (short): "
        f"{click.style(gpg_key.get('fingerprint_short') or '(none)', fg='green')}"
    )
    click.echo(f"Active: {click.style(str(bool(gpg_key.get('active'))), fg='blue')}")
    click.echo(f"Default: {click.style(str(bool(gpg_key.get('default'))), fg='blue')}")

    comment = gpg_key.get("comment")
    if comment:
        click.echo(f"Comment: {comment}")

    public_key = gpg_key.get("public_key")
    if public_key:
        click.echo()
        click.echo("Public Key:")
        click.echo(public_key)

    click.echo()


@repositories.group(cls=command.AliasGroup, name="gpg", aliases=[])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def gpg(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage a repository's GPG signing key.

    See the help for subcommands for more information on each.

    Note: The API doesn't currently support deleting a repository's GPG key,
    so there's no 'delete' subcommand here.
    """


@gpg.command(name="get", aliases=["list", "ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.pass_context
def gpg_get(ctx, opts, owner_repo):
    """
    Get the active GPG signing key for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to get the GPG key for, separated by a slash.

        Example: 'your-org/your-repo'

    Full CLI example:

      $ cloudsmith repos gpg get your-org/your-repo
    """
    owner, repo = owner_repo
    use_stderr = utils.should_use_stderr(opts)

    click.echo("Getting GPG key ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get the repository GPG key!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        gpg_key = api.list_repo_gpg_key(owner, repo)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, gpg_key):
        return

    print_gpg_key(gpg_key)


@gpg.command(name="upload", aliases=["set"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "--private-key-file",
    "private_key_file",
    type=click.File("r"),
    required=True,
    help="Path to a file containing the armored GPG private key to upload. "
    "Use '-' to read from stdin.",
)
@click.option(
    "--passphrase-file",
    "passphrase_file",
    type=click.File("r"),
    required=False,
    default=None,
    help="Path to a file containing the GPG private key's passphrase. If "
    "omitted, you'll be prompted for it interactively (leave blank if the "
    "key has none). The passphrase is never accepted as a plain "
    "command-line value, to avoid leaking it into shell history or the "
    "process list.",
)
@click.pass_context
def gpg_upload(ctx, opts, owner_repo, private_key_file, passphrase_file):
    """
    Set (upload) the active GPG signing key for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to set the GPG key for, separated by a slash.

        Example: 'your-org/your-repo'

    The private key material is always read from a file (or stdin via '-'),
    never accepted as a plain command-line argument.

    Full CLI example:

      $ cloudsmith repos gpg upload your-org/your-repo --private-key-file key.asc
    """
    owner, repo = owner_repo
    use_stderr = utils.should_use_stderr(opts)

    gpg_private_key = private_key_file.read()
    if not gpg_private_key.strip():
        raise click.BadParameter(
            "The private key file is empty.", param_hint="--private-key-file"
        )

    if passphrase_file is not None:
        gpg_passphrase = passphrase_file.read().strip() or None
    else:
        gpg_passphrase = (
            click.prompt(
                "GPG passphrase (leave blank if the key has none)",
                hide_input=True,
                default="",
                show_default=False,
            ).strip()
            or None
        )

    click.echo(
        f"Uploading GPG key for {click.style(repo, bold=True)} in the "
        f"{click.style(owner, bold=True)} namespace ... ",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to set the repository GPG key!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        gpg_key = api.create_repo_gpg_key(
            owner, repo, gpg_private_key=gpg_private_key, gpg_passphrase=gpg_passphrase
        )

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, gpg_key):
        return

    print_gpg_key(gpg_key)


@gpg.command(name="regenerate", aliases=["regen"])
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
def gpg_regenerate(ctx, opts, owner_repo, yes):
    """
    Regenerate the GPG signing key for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to regenerate the GPG key for, separated by a slash.

        Example: 'your-org/your-repo'

    This replaces the repository's current GPG key with a newly generated
    one; consumers relying on the old key's fingerprint will need to pick up
    the new one. There is no way to undo this from the CLI.

    Full CLI example:

      $ cloudsmith repos gpg regenerate your-org/your-repo
    """
    owner, repo = owner_repo
    use_stderr = utils.should_use_stderr(opts)

    prompt = (
        f"regenerate the GPG key for {click.style(repo, bold=True)} in the "
        f"{click.style(owner, bold=True)} namespace"
    )
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    click.echo("Regenerating GPG key ... ", nl=False, err=use_stderr)

    context_msg = "Failed to regenerate the repository GPG key!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        gpg_key = api.regenerate_repo_gpg_key(owner, repo)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, gpg_key):
        return

    print_gpg_key(gpg_key)


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

    prompt = "delete the {repository} from the {namespace} namespace".format(
        **delete_args
    )
    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    click.secho(
        "Deleting {repository} from the {namespace} namespace ... ".format(
            **delete_args
        ),
        nl=False,
    )

    context_msg = "Failed to delete the repository!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        api.delete_repo(owner=owner, repo=repo)

    click.secho("OK", fg="green")
