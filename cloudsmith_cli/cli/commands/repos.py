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


#: Reasons for the API failures a person can actually act on, keyed by
#: status. Anything not listed here keeps the standard error rendering.
GPG_READ_ERROR_REASONS = {404: "not found"}
GPG_WRITE_ERROR_REASONS = {
    400: "the provided key is not valid",
    402: "custom GPG keys require a paid plan",
    404: "not found",
}

REGENERATE_CONFIRMATION_WORD = "regenerate"

REGENERATE_WARNING = (
    "Regenerating a repository's GPG key is irrevocable. The old key is discarded\n"
    "and every consumer verifying against its fingerprint will need to fetch and\n"
    "trust the new one before their next install succeeds."
)


class SecretFile(click.File):
    """A ``click.File`` that also records the literal value it was given.

    ``click.File`` builds a brand new stream object for ``-`` every time it
    converts a value, so the stdin-conflict checks in ``gpg upload`` cannot
    be made by comparing the returned stream against
    ``click.get_text_stream("stdin")``: that identity happens to hold under
    ``CliRunner`` but never holds in a real process, which would leave the
    checks silently inert exactly where they matter. Recording the raw
    value instead makes them exact in both.
    """

    #: Key under which the raw values are stashed on the click context.
    META_KEY = "cloudsmith_cli.secret_file_sources"

    def convert(self, value, param, ctx):
        stream = super().convert(value, param, ctx)
        if ctx is not None and param is not None and isinstance(value, str):
            ctx.meta.setdefault(self.META_KEY, {})[param.name] = value
        return stream


def secret_file_is_stdin(ctx, param_name):
    """Check whether a secret file parameter was given as '-' (i.e. stdin)."""
    return ctx.meta.get(SecretFile.META_KEY, {}).get(param_name) == "-"


def gpg_error_summaries(action, repo, reasons):
    """Build single-line error messages for a GPG command, keyed by status."""
    return {
        status: f"Could not {action} GPG key for {repo}: {reason}."
        for status, reason in reasons.items()
    }


def stdin_is_a_terminal():
    """Check whether stdin is attached to a terminal."""
    return click.get_text_stream("stdin").isatty()


def confirm_regenerate(err=False):
    """Ask for typed confirmation before regenerating a repository's GPG key.

    Returns True only if the exact confirmation word was typed. Raises a
    usage error when there's no terminal to ask, so an unattended run fails
    fast instead of blocking on a question nobody can answer.
    """
    if not stdin_is_a_terminal():
        raise click.UsageError(
            "Refusing to regenerate the GPG key without confirmation: stdin is "
            "not a terminal. Pass -y/--yes to confirm non-interactively."
        )

    click.echo(err=err)
    click.echo(REGENERATE_WARNING, err=err)
    click.echo(err=err)

    answer = click.prompt(
        f"Type '{REGENERATE_CONFIRMATION_WORD}' to confirm",
        default="",
        show_default=False,
        err=err,
    )

    if answer.strip() == REGENERATE_CONFIRMATION_WORD:
        return True

    click.echo(err=err)
    click.secho("Not confirmed. No changes made.", fg="yellow", err=err)
    return False


@repositories.group(cls=command.AliasGroup, name="gpg", aliases=[])
@click.pass_context
def gpg(ctx):  # pylint: disable=unused-argument
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
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg=context_msg,
            error_summaries=gpg_error_summaries("get", repo, GPG_READ_ERROR_REASONS),
        ),
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
    type=SecretFile("r"),
    required=True,
    help="Path to a file containing the armored GPG private key to upload. "
    "Use '-' to read from stdin; in that case --passphrase-file must be a "
    "file path.",
)
@click.option(
    "--passphrase-file",
    "passphrase_file",
    type=SecretFile("r"),
    required=False,
    default=None,
    help="Path to a file containing the GPG private key's passphrase. If "
    "omitted, you'll be prompted for it interactively (leave blank if the "
    "key has none). One trailing line ending is ignored. Use '-' to read "
    "from stdin only when --private-key-file is a path. The passphrase is "
    "never accepted as a plain command-line value, to avoid leaking it "
    "into shell history or the process list.",
)
@click.option(
    "-n",
    "--dry-run",
    "dry_run",
    default=False,
    is_flag=True,
    help="Validate the inputs and show what would be uploaded, without "
    "changing the repository's key.",
)
@click.pass_context
def gpg_upload(ctx, opts, owner_repo, private_key_file, passphrase_file, dry_run):
    """
    Set (upload) the active GPG signing key for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to set the GPG key for, separated by a slash.

        Example: 'your-org/your-repo'

    The private key material is always read from a file (or stdin via '-'),
    never accepted as a plain command-line argument.

    Use -n/--dry-run to validate the key and passphrase inputs without
    changing the repository's key.

    Full CLI example:

      $ cloudsmith repos gpg upload your-org/your-repo --private-key-file key.asc
    """
    owner, repo = owner_repo
    use_stderr = utils.should_use_stderr(opts)

    if opts.debug:
        raise click.BadParameter(
            "Debug output is disabled for this command because the request "
            "contains private key material and a passphrase.",
            param_hint="--debug",
        )

    private_key_from_stdin = secret_file_is_stdin(ctx, "private_key_file")
    passphrase_from_stdin = secret_file_is_stdin(ctx, "passphrase_file")
    if private_key_from_stdin and (passphrase_file is None or passphrase_from_stdin):
        raise click.BadParameter(
            "Must be a file path (not '-') when --private-key-file is '-'.",
            param_hint="--passphrase-file",
        )

    gpg_private_key = private_key_file.read()
    if not gpg_private_key.strip():
        raise click.BadParameter(
            "The private key file is empty.", param_hint="--private-key-file"
        )

    if passphrase_file is not None:
        gpg_passphrase = passphrase_file.read()
        if gpg_passphrase.endswith("\r\n"):
            gpg_passphrase = gpg_passphrase[:-2]
        elif gpg_passphrase.endswith(("\r", "\n")):
            gpg_passphrase = gpg_passphrase[:-1]
    elif stdin_is_a_terminal():
        gpg_passphrase = click.prompt(
            "GPG passphrase (leave blank if the key has none)",
            hide_input=True,
            default="",
            show_default=False,
            err=use_stderr,
        )
    else:
        # Nothing to prompt: an unattended run would block on a question
        # nobody can answer, so take the key to be unencrypted instead.
        gpg_passphrase = ""
    if gpg_passphrase == "":
        gpg_passphrase = None

    if dry_run:
        if utils.maybe_print_as_json(
            opts,
            {
                "dry_run": True,
                "action": "upload",
                "namespace": owner,
                "repository": repo,
                "passphrase_supplied": gpg_passphrase is not None,
            },
        ):
            return

        click.secho(
            f"Would upload the GPG key for {click.style(repo, bold=True)} in the "
            f"{click.style(owner, bold=True)} namespace "
            f"({'with' if gpg_passphrase is not None else 'without'} a passphrase). "
            "Nothing sent - this was a dry run.",
            fg="yellow",
            err=use_stderr,
        )
        return

    click.echo(
        f"Uploading GPG key for {click.style(repo, bold=True)} in the "
        f"{click.style(owner, bold=True)} namespace ... ",
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to set the repository GPG key!"
    with (
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg=context_msg,
            error_summaries=gpg_error_summaries("set", repo, GPG_WRITE_ERROR_REASONS),
        ),
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
@click.option(
    "-n",
    "--dry-run",
    "dry_run",
    default=False,
    is_flag=True,
    help="Show what would be regenerated, without changing the repository's key.",
)
@click.pass_context
def gpg_regenerate(ctx, opts, owner_repo, yes, dry_run):
    """
    Regenerate the GPG signing key for a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to regenerate the GPG key for, separated by a slash.

        Example: 'your-org/your-repo'

    This replaces the repository's current GPG key with a newly generated
    one; consumers relying on the old key's fingerprint will need to pick up
    the new one. There is no way to undo this from the CLI.

    Because of that, the command asks you to type 'regenerate' to confirm.
    Unattended runs never block on that question: with no terminal attached
    the command fails unless -y/--yes was passed.

    Full CLI example:

      $ cloudsmith repos gpg regenerate your-org/your-repo
    """
    owner, repo = owner_repo
    use_stderr = utils.should_use_stderr(opts)

    if dry_run:
        if utils.maybe_print_as_json(
            opts,
            {
                "dry_run": True,
                "action": "regenerate",
                "namespace": owner,
                "repository": repo,
            },
        ):
            return

        click.secho(
            f"Would regenerate the GPG key for {click.style(repo, bold=True)} in "
            f"the {click.style(owner, bold=True)} namespace. Nothing sent - this "
            "was a dry run.",
            fg="yellow",
            err=use_stderr,
        )
        return

    if not yes and not confirm_regenerate(err=use_stderr):
        return

    click.echo("Regenerating GPG key ... ", nl=False, err=use_stderr)

    context_msg = "Failed to regenerate the repository GPG key!"
    with (
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg=context_msg,
            error_summaries=gpg_error_summaries(
                "regenerate", repo, GPG_WRITE_ERROR_REASONS
            ),
        ),
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
