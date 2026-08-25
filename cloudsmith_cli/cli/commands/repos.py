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


PRIVILEGE_LEVELS = ("read", "write", "admin")

# A privilege names a team, a user or a service account, never more than one,
# which is why the table has a Type/Name pair rather than a column per kind.
TARGET_KINDS = ("team", "user", "service")


def get_privilege_target(entry):
    """Get the (kind, name) pair a privilege entry applies to, if any."""
    for kind in TARGET_KINDS:
        name = entry.get(kind)
        if name:
            return kind, name
    return None


def as_privilege_entry(target, privilege):
    """Build the compact entry shape the API accepts on write.

    A listed privilege carries every target key, with null for the two that
    don't apply, and the write endpoints reject those nulls outright.
    """
    kind, name = target
    return {"privilege": privilege, kind: name}


def print_privileges(opts, data, show_list_info=True):
    """Print repository privileges as a table or output in another format."""
    headers = ["Type", "Name", "Privilege"]

    targeted = [(get_privilege_target(entry), entry) for entry in data]
    rows = []
    for target, entry in sorted(targeted, key=lambda item: item[0] or ("", "")):
        kind, name = target or ("", "")
        rows.append(
            [
                click.style(kind.capitalize(), fg="yellow"),
                click.style(name, fg="magenta"),
                click.style(entry.get("privilege") or "", fg="cyan"),
            ]
        )

    if rows:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    if not show_list_info:
        return

    num_results = len(rows)
    utils.pretty_print_list_info(
        num_results=num_results,
        suffix="privilege%s" % ("s" if num_results != 1 else ""),
        page_all=True,
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


@repositories.group(cls=command.AliasGroup, name="privileges", aliases=["privilege"])
def privileges():
    """
    Manage explicit team/user/service privileges on a repository.

    See the help for subcommands for more information on each.
    """


def collect_privilege_targets(teams, users, services):
    """Turn the repeated --team/--user/--service options into targets."""
    targets = []
    seen = set()

    for kind, names in zip(TARGET_KINDS, (teams, users, services)):
        for name in names:
            if not name.strip():
                raise click.UsageError(f"Specify a slug for --{kind}.")

            if (kind, name) in seen:
                raise click.UsageError(f"Specified more than once: {kind} {name}.")
            seen.add((kind, name))
            targets.append((kind, name))

    if not targets:
        raise click.UsageError("Specify at least one of --team, --user or --service.")

    return targets


def describe_privilege_targets(targets):
    """Describe targets for a message, e.g. 'team eng, service ci'."""
    return ", ".join(f"{kind} {click.style(name, bold=True)}" for kind, name in targets)


def summarise_privileges_error(action, repo):
    """Build a summariser that renders privilege rejections as one sentence.

    The API reports a rejected privilege as a field-indexed 422, which reads
    as three lines of machine detail. The person running the command only
    needs to know which repository was not changed and why. Every other
    status keeps the standard rendering, because the status code is the part
    that matters when the request failed for some other reason.
    """

    def summarise(exc, detail, fields):
        # Without fields there is nothing better to say than the standard
        # rendering: `detail` falls back to the status description, which
        # would read as "unprocessable Entity" and lose the status code.
        if exc.status != 422 or not fields:
            return None

        messages = []
        for value in fields.values():
            if isinstance(value, (list, tuple)):
                value = " ".join(str(item) for item in value)
            messages.append(str(value))

        message = " ".join(messages).strip().rstrip(".")
        if not message:
            return None

        # The API capitalises these as standalone sentences; lower the first
        # letter to join it onto ours, unless it starts an acronym.
        if message[:2].istitle() or len(message) == 1:
            message = message[0].lower() + message[1:]

        return f"Could not {action} privileges for {repo}: {message}"

    return summarise


@privileges.command(name="list", aliases=["ls", "get"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.pass_context
def privileges_list(ctx, opts, owner_repo):
    """
    List the explicit team/user/service privileges on a repository.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to list privileges for. All separated by a slash.

        Example: 'your-org/your-repo'

    Only explicitly granted privileges are listed here; this does not include
    access implied by organisation role, team membership or ownership, none of
    which these commands can change. The endpoint returns every privilege at
    once, so there is nothing to page through.

    Full CLI example:

      $ cloudsmith repos privileges list your-org/your-repo
    """
    owner, repo = owner_repo

    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)

    click.echo("Getting list of repository privileges ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get list of repository privileges!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        privileges_ = api.list_repo_privileges(owner=owner, repo=repo)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, privileges_):
        return

    print_privileges(opts=opts, data=privileges_)


@privileges.command(name="set")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "--team",
    "teams",
    multiple=True,
    help="A team (slug) to grant the privilege to. Repeatable.",
)
@click.option(
    "--user",
    "users",
    multiple=True,
    help="A user (slug) to grant the privilege to. Repeatable.",
)
@click.option(
    "--service",
    "services",
    multiple=True,
    help="A service account (slug) to grant the privilege to. Repeatable.",
)
@click.option(
    "--privilege",
    required=True,
    type=click.Choice(PRIVILEGE_LEVELS, case_sensitive=False),
    help="The privilege level to grant.",
)
@click.pass_context
def privileges_set(ctx, opts, owner_repo, teams, users, services, privilege):
    """
    Grant a privilege to teams, users and/or service accounts.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to set privileges on. All separated by a slash.

        Example: 'your-org/your-repo'

    At least one of --team, --user or --service must be given, and each may be
    repeated to give several targets the same privilege in one call.

    This only ever adds or raises access: a target that already has an
    explicit privilege is updated in place, and anything not named is left
    exactly as it was. That makes it safe to run in a pipeline without reading
    the current privileges first, and safe to run twice.

    Full CLI example:

      $ cloudsmith repos privileges set your-org/your-repo --team your-team --privilege write
    """
    owner, repo = owner_repo
    targets = collect_privilege_targets(teams, users, services)

    # The API accepts any casing but always stores and echoes its own, so
    # normalise here to keep the CLI's own output consistent with a later list.
    privilege = privilege.capitalize()
    entries = [as_privilege_entry(target, privilege) for target in targets]

    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        f"Granting {click.style(privilege, bold=True)} on "
        f"{click.style(repo, bold=True)} in the {click.style(owner, bold=True)} "
        f"namespace to {describe_privilege_targets(targets)} ... ",
        nl=False,
        err=use_stderr,
    )

    with (
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg="Failed to set the repository privileges!",
            summarise_error=summarise_privileges_error("set", repo),
        ),
        maybe_spinner(opts),
    ):
        api.update_repo_privileges(owner, repo, entries)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, entries):
        return

    print_privileges(opts=opts, data=entries)


@privileges.command(name="revoke")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.option(
    "--team",
    "teams",
    multiple=True,
    help="A team (slug) to revoke the privilege of. Repeatable.",
)
@click.option(
    "--user",
    "users",
    multiple=True,
    help="A user (slug) to revoke the privilege of. Repeatable.",
)
@click.option(
    "--service",
    "services",
    multiple=True,
    help="A service account (slug) to revoke the privilege of. Repeatable.",
)
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def privileges_revoke(ctx, opts, owner_repo, teams, users, services, yes):
    """
    Revoke the explicit privileges of teams, users and/or service accounts.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to revoke privileges on. All separated by a slash.

        Example: 'your-org/your-repo'

    At least one of --team, --user or --service must be given, and each may be
    repeated. Targets with no explicit privilege are named and skipped, so
    running this twice is a no-op rather than a failure.

    The API cannot delete a single privilege, so this reads the current
    privileges and writes back the ones being kept. A change made by someone
    else in between can therefore be lost.

    Full CLI example:

      $ cloudsmith repos privileges revoke your-org/your-repo --team your-team
    """
    owner, repo = owner_repo
    targets = collect_privilege_targets(teams, users, services)

    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)

    click.echo("Getting list of repository privileges ... ", nl=False, err=use_stderr)

    context_msg = "Failed to get list of repository privileges!"
    with (
        handle_api_exceptions(ctx, opts=opts, context_msg=context_msg),
        maybe_spinner(opts),
    ):
        current = api.list_repo_privileges(owner=owner, repo=repo)

    click.secho("OK", fg="green", err=use_stderr)

    # Revoking means writing the whole list back, so every entry that stays
    # has to be one this CLI can express. Rather than silently dropping an
    # entry it can't read, or writing back the nulls the endpoint rejects,
    # say so and point at the command that can express anything.
    for entry in current:
        if get_privilege_target(entry) is None or not entry.get("privilege"):
            raise click.ClickException(
                "This repository has a privilege this version of the CLI "
                "doesn't understand, and revoking would drop it. Use "
                "'cloudsmith repos privileges replace' to state the whole "
                "list explicitly, or upgrade the CLI."
            )

    classified = [(get_privilege_target(entry), entry) for entry in current]
    existing = {target for target, _ in classified}
    found = [target for target in targets if target in existing]

    for kind, name in targets:
        if (kind, name) not in existing:
            click.secho(
                f"No explicit privilege for {kind} {name}, skipping.",
                fg="yellow",
                err=use_stderr,
            )

    if not found:
        click.secho("Nothing to revoke.", fg="green", err=use_stderr)
        # The command ran to completion, so a `-F json` consumer still gets a
        # document to parse: the privileges, unchanged.
        utils.maybe_print_as_json(
            opts,
            [
                as_privilege_entry(target, entry.get("privilege"))
                for target, entry in classified
            ],
        )
        return

    prompt = (
        f"Revoke the privileges of {describe_privilege_targets(found)} on "
        f"{click.style(repo, bold=True)} in the {click.style(owner, bold=True)} "
        "namespace"
    )
    # Declining writes nothing, so there is nothing to report: both revoke and
    # replace leave stdout empty rather than implying a result.
    if not utils.confirm_operation(prompt, prefix="", assume_yes=yes, err=use_stderr):
        return

    kept = [
        as_privilege_entry(target, entry.get("privilege"))
        for target, entry in classified
        if target not in found
    ]

    click.echo(
        f"Revoking the privileges of {describe_privilege_targets(found)} ... ",
        nl=False,
        err=use_stderr,
    )

    with (
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg="Failed to revoke the repository privileges!",
            summarise_error=summarise_privileges_error("revoke", repo),
        ),
        maybe_spinner(opts),
    ):
        api.replace_repo_privileges(owner, repo, kept)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, kept):
        return

    print_privileges(opts=opts, data=kept)


def read_privileges_file(privileges_file):
    """Read and validate the privileges declared in a JSON file."""
    param_hint = "PRIVILEGES_FILE"

    try:
        document = json.load(privileges_file)
    except ValueError as exc:
        raise click.BadParameter(f"Invalid JSON: {exc}", param_hint=param_hint)

    if isinstance(document, dict):
        document = document.get("privileges")

    if not isinstance(document, list):
        raise click.BadParameter(
            "Expected a list of privileges, or an object with a 'privileges' list.",
            param_hint=param_hint,
        )

    entries = []
    seen = set()
    for entry in document:
        if not isinstance(entry, dict):
            raise click.BadParameter(
                "Each privilege must be an object.", param_hint=param_hint
            )

        named = [kind for kind in TARGET_KINDS if entry.get(kind)]
        if len(named) != 1:
            raise click.BadParameter(
                "Each privilege needs exactly one of 'team', 'user' or 'service'.",
                param_hint=param_hint,
            )

        kind = named[0]
        name = entry[kind]
        if not isinstance(name, str):
            raise click.BadParameter(
                f"The '{kind}' of a privilege must be a slug, not {name!r}.",
                param_hint=param_hint,
            )

        if (kind, name) in seen:
            raise click.BadParameter(
                f"Specified more than once: {kind} {name}.", param_hint=param_hint
            )
        seen.add((kind, name))

        privilege = str(entry.get("privilege") or "")
        if privilege.lower() not in PRIVILEGE_LEVELS:
            raise click.BadParameter(
                f"'{privilege}' is not one of "
                + ", ".join(f"'{level}'" for level in PRIVILEGE_LEVELS)
                + ".",
                param_hint=param_hint,
            )

        entries.append(as_privilege_entry((kind, name), privilege.capitalize()))

    return entries


@privileges.command(name="replace")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.argument("privileges_file", metavar="PRIVILEGES_FILE", type=click.File("r"))
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def privileges_replace(ctx, opts, owner_repo, privileges_file, yes):
    """
    Replace every explicit privilege on a repository with those in a file.

    - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
      REPO name to replace privileges on. All separated by a slash.

        Example: 'your-org/your-repo'

    - PRIVILEGES_FILE: A JSON file holding either a list of privileges or an
      object with a 'privileges' list. Use '-' to read it from stdin, which
      needs -y because the confirmation has nowhere left to read an answer.

    The file becomes the complete truth for the repository, so anything absent
    from it loses its explicit access, including you. Each entry names exactly
    one of 'team', 'user' or 'service', plus a 'privilege' of 'read', 'write'
    or 'admin'. A file listing nothing revokes every explicit privilege, which
    the confirmation says in those words.

    Full CLI example:

      $ cloudsmith repos privileges replace your-org/your-repo privileges.json
    """
    owner, repo = owner_repo

    # The file and the answer to the prompt would come from the same stream,
    # so reading one leaves nothing to read the other from.
    if not yes and getattr(privileges_file, "name", None) in ("-", "<stdin>"):
        raise click.UsageError(
            "Reading the privileges from stdin leaves nothing to answer the "
            "confirmation with. Pass -y to confirm up front."
        )

    entries = read_privileges_file(privileges_file)

    # Use stderr for messages if the output is something else (e.g. JSON)
    use_stderr = utils.should_use_stderr(opts)

    if entries:
        prompt = (
            "Replace all {count} privilege{plural} on {repo} in the {owner} "
            "namespace, removing any not listed".format(
                count=len(entries),
                plural="" if len(entries) == 1 else "s",
                repo=click.style(repo, bold=True),
                owner=click.style(owner, bold=True),
            )
        )
    else:
        # "Replace all 0 privileges" reads as a no-op and is the opposite:
        # an empty file revokes every explicit privilege on the repository.
        prompt = (
            "The file lists no privileges. Revoke all explicit access to "
            f"{click.style(repo, bold=True)} in the "
            f"{click.style(owner, bold=True)} namespace"
        )
    if not utils.confirm_operation(prompt, prefix="", assume_yes=yes, err=use_stderr):
        return

    click.echo(
        f"Replacing the privileges on {click.style(repo, bold=True)} in the "
        f"{click.style(owner, bold=True)} namespace ... ",
        nl=False,
        err=use_stderr,
    )

    with (
        handle_api_exceptions(
            ctx,
            opts=opts,
            context_msg="Failed to replace the repository privileges!",
            summarise_error=summarise_privileges_error("replace", repo),
        ),
        maybe_spinner(opts),
    ):
        api.replace_repo_privileges(owner, repo, entries)

    click.secho("OK", fg="green", err=use_stderr)

    if utils.maybe_print_as_json(opts, entries):
        return

    print_privileges(opts=opts, data=entries)
