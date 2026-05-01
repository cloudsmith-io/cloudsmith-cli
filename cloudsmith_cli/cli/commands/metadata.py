"""CLI/Commands - Manage metadata attached to packages."""

import json

import click

from ...core.api.metadata import (
    create_metadata as api_create_metadata,
    delete_metadata as api_delete_metadata,
    get_metadata as api_get_metadata,
    list_metadata as api_list_metadata,
    normalise_classification,
    normalise_source_kind,
    update_metadata as api_update_metadata,
)
from ...core.api.packages import get_package_slug_perm as api_get_package_slug_perm
from ...core.pagination import paginate_results
from ...core.version import get_version as get_cli_version
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main

_METADATA_HEADERS = [
    "Slug",
    "Content Type",
    "Classification",
    "Source Kind",
    "Source Identity",
]


def _default_source_identity():
    """Return the default value for --source-identity."""
    return f"cloudsmith-cli@{get_cli_version()}"


def _format_metadata_row(entry):
    return [
        click.style(entry.get("slug_perm") or "", fg="cyan"),
        click.style(entry.get("content_type") or "", fg="yellow"),
        click.style(str(entry.get("classification", "")), fg="magenta"),
        click.style(str(entry.get("source_kind", "")), fg="blue"),
        click.style(entry.get("source_identity") or "", fg="green"),
    ]


def _echo_action(message, use_stderr):
    """Print an in-progress status message."""
    click.echo(message, nl=False, err=use_stderr)


def _print_metadata_table(opts, entries, page_info=None, page_all=False):
    """Print a list of metadata entries as a table or JSON."""
    if utils.maybe_print_as_json(opts, list(entries), page_info=page_info):
        return

    rows = [
        _format_metadata_row(e)
        for e in sorted(entries, key=lambda e: e.get("slug_perm") or "")
    ]

    if rows:
        click.echo()
        utils.pretty_print_table(_METADATA_HEADERS, rows)

    click.echo()

    num_results = len(rows)
    list_suffix = "metadata entr%s" % ("ies" if num_results != 1 else "y")
    utils.pretty_print_list_info(
        num_results=num_results,
        page_info=None if page_all else page_info,
        suffix=f"{list_suffix} retrieved" if page_all else f"{list_suffix} visible",
        page_all=page_all,
    )


def _print_metadata_entry(opts, entry):
    """Print a single metadata entry as a table + indented JSON content."""
    if utils.maybe_print_as_json(opts, entry):
        return

    click.echo()
    utils.pretty_print_table(_METADATA_HEADERS, [_format_metadata_row(entry)])
    click.echo()

    content = entry.get("content")
    if content is not None:
        click.secho("Content:", bold=True)
        click.echo(json.dumps(content, indent=2, sort_keys=True))


def _load_content(content_file, inline_content, *, required):
    """Resolve --file / --content into a parsed object.

    Enforces the XOR between the two sources. When `required` is True (used
    by `add`), at least one source must be provided. When False (used by
    `update`), a missing source means "do not change content".
    """
    if content_file is not None and inline_content is not None:
        raise click.UsageError("--file and --content are mutually exclusive.")

    if content_file is not None:
        if content_file == "-":
            raw, source = click.get_text_stream("stdin").read(), "stdin"
        else:
            with open(content_file, encoding="utf-8") as fh:
                raw, source = fh.read(), "--file"
    elif inline_content is not None:
        raw, source = inline_content, "--content"
    elif required:
        raise click.UsageError("One of --file or --content is required.")
    else:
        return None

    try:
        return json.loads(raw)
    except ValueError as exc:
        raise click.UsageError(f"Invalid JSON in {source}: {exc}") from exc


@main.group(name="metadata", cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def metadata_(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage metadata attached to packages in a repository.

    See the help for subcommands for more information on each.
    """


@metadata_.command(name="list", aliases=["ls"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_cli_list_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("metadata_slug_perm", required=False, default=None)
@click.option(
    "--source-kind",
    "source_kind",
    default=None,
    help=(
        "Filter by metadata source kind. Accepts an integer or a name "
        "(e.g. 'customer', 'third_party'). Ignored when METADATA_SLUG_PERM is given."
    ),
)
@click.option(
    "--classification",
    "classification",
    default=None,
    help=(
        "Filter by metadata classification. Accepts an integer or a name "
        "(e.g. 'provenance', 'sbom'). Ignored when METADATA_SLUG_PERM is given."
    ),
)
@click.pass_context
def list_metadata(
    ctx,
    opts,
    owner_repo_package,
    metadata_slug_perm,
    page,
    page_size,
    page_all,
    source_kind,
    classification,
):
    """
    List metadata entries attached to a package.

    OWNER/REPO/PACKAGE: identifies the package whose metadata you want to list.

    METADATA_SLUG_PERM (optional): if given, fetch and display only that single
    metadata entry. Pagination and filter flags are ignored in this case.

    \b
    Examples:
      $ cloudsmith metadata list your-org/awesome-repo/better-pkg
      $ cloudsmith metadata list your-org/awesome-repo/better-pkg --classification provenance
      $ cloudsmith metadata list your-org/awesome-repo/better-pkg meta-slug-perm
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    if metadata_slug_perm:
        _echo_action(
            "Fetching metadata entry %(metadata)s for the '%(package)s' package ... "
            % {
                "metadata": click.style(metadata_slug_perm, bold=True),
                "package": click.style(package, bold=True),
            },
            use_stderr,
        )

        context_msg = "Failed to fetch metadata for the package!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                slug_perm = api_get_package_slug_perm(
                    owner=owner, repo=repo, identifier=package
                )
                entry = api_get_metadata(slug_perm, metadata_slug_perm)

        click.secho("OK", fg="green", err=use_stderr)
        _print_metadata_entry(opts, entry)
        return

    # Validate filter values up-front for a friendlier error than what the
    # API would return (the normalisers raise ValueError on invalid values).
    try:
        normalise_source_kind(source_kind)
        normalise_classification(classification)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    _echo_action(
        "Listing metadata for the '%(package)s' package ... "
        % {"package": click.style(package, bold=True)},
        use_stderr,
    )

    context_msg = "Failed to list metadata for the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            slug_perm = api_get_package_slug_perm(
                owner=owner, repo=repo, identifier=package
            )
            entries, page_info = paginate_results(
                api_list_metadata,
                page_all=page_all,
                page=page,
                page_size=page_size,
                package_slug_perm=slug_perm,
                source_kind=source_kind,
                classification=classification,
            )

    click.secho("OK", fg="green", err=use_stderr)
    _print_metadata_table(opts, entries, page_info=page_info, page_all=page_all)


@metadata_.command(name="add")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.option(
    "--content-type",
    "content_type",
    required=True,
    help=(
        "The content type of the metadata payload (e.g. 'application/json'). "
        "Content type is immutable after creation."
    ),
)
@click.option(
    "--file",
    "content_file",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=True,
    ),
    default=None,
    help="Path to a JSON file containing the metadata content. Use '-' for stdin.",
)
@click.option(
    "--content",
    "inline_content",
    default=None,
    help=("Inline JSON content for the metadata. Mutually exclusive with --file."),
)
@click.option(
    "--source-identity",
    "source_identity",
    default=None,
    help=(
        "Free-text identifier indicating where this metadata originated. "
        "Defaults to 'cloudsmith-cli@<version>'."
    ),
)
@click.pass_context
def add_metadata(
    ctx,
    opts,
    owner_repo_package,
    content_type,
    content_file,
    inline_content,
    source_identity,
):
    """
    Attach a new metadata entry to a package.

    OWNER/REPO/PACKAGE: the package the metadata should be attached to.

    Exactly one of --file or --content must be supplied.
    Content type is set on creation and cannot be changed later.

    \b
    Examples:
      $ cloudsmith metadata add your-org/awesome-repo/better-pkg \\
            --content-type application/json \\
            --content '{"foo": "bar"}'
      $ cat payload.json | cloudsmith metadata add your-org/awesome-repo/better-pkg \\
            --content-type application/json \\
            --file -
      $ cloudsmith metadata add your-org/awesome-repo/better-pkg \\
            --content-type application/vnd.jfrog.buildinfo+json \\
            --file buildinfo.json
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    content = _load_content(content_file, inline_content, required=True)
    source_identity = source_identity or _default_source_identity()

    _echo_action(
        "Attaching metadata to the '%(package)s' package ... "
        % {"package": click.style(package, bold=True)},
        use_stderr,
    )

    context_msg = "Failed to attach metadata to the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            slug_perm = api_get_package_slug_perm(
                owner=owner, repo=repo, identifier=package
            )
            entry = api_create_metadata(
                slug_perm,
                content=content,
                content_type=content_type,
                source_identity=source_identity,
            )

    click.secho("OK", fg="green", err=use_stderr)
    _print_metadata_entry(opts, entry)


@metadata_.command(name="update")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("metadata_slug_perm")
@click.option(
    "--file",
    "content_file",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=True,
    ),
    default=None,
    help=(
        "Path to a JSON file containing replacement metadata content. "
        "Use '-' for stdin."
    ),
)
@click.option(
    "--content",
    "inline_content",
    default=None,
    help=(
        "Inline JSON replacement content for the metadata. Mutually exclusive "
        "with --file."
    ),
)
@click.option(
    "--source-identity",
    "source_identity",
    default=None,
    help="Update the free-text source identity for this metadata entry.",
)
@click.pass_context
def update_metadata(
    ctx,
    opts,
    owner_repo_package,
    metadata_slug_perm,
    content_file,
    inline_content,
    source_identity,
):
    """
    Patch an existing metadata entry on a package.

    OWNER/REPO/PACKAGE: the package the metadata is attached to.
    METADATA_SLUG_PERM: the permanent slug of the metadata entry to update.

    Content type cannot be changed after creation.

    \b
    Examples:
      $ cloudsmith metadata update your-org/awesome-repo/better-pkg meta-slug \\
            --content '{"foo": "baz"}'
      $ cat payload.json | cloudsmith metadata update your-org/awesome-repo/better-pkg meta-slug \\
            --file -
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    content = _load_content(content_file, inline_content, required=False)

    patch_kwargs = {
        key: value
        for key, value in (
            ("content", content),
            ("source_identity", source_identity),
        )
        if value is not None
    }
    if not patch_kwargs:
        raise click.UsageError(
            "Nothing to update. Provide --file, --content, or --source-identity."
        )

    _echo_action(
        "Updating metadata entry %(metadata)s on the '%(package)s' package ... "
        % {
            "metadata": click.style(metadata_slug_perm, bold=True),
            "package": click.style(package, bold=True),
        },
        use_stderr,
    )

    context_msg = "Failed to update metadata on the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            slug_perm = api_get_package_slug_perm(
                owner=owner, repo=repo, identifier=package
            )
            entry = api_update_metadata(slug_perm, metadata_slug_perm, **patch_kwargs)

    click.secho("OK", fg="green", err=use_stderr)
    _print_metadata_entry(opts, entry)


@metadata_.command(name="remove", aliases=["rm"])
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
)
@click.argument("metadata_slug_perm")
@click.option(
    "-y",
    "--yes",
    default=False,
    is_flag=True,
    help="Assume yes as default answer to questions (this is dangerous!)",
)
@click.pass_context
def remove_metadata(ctx, opts, owner_repo_package, metadata_slug_perm, yes):
    """
    Remove a metadata entry from a package.

    OWNER/REPO/PACKAGE: the package the metadata is attached to.
    METADATA_SLUG_PERM: the permanent slug of the metadata entry to delete.

    \b
    Example:
      $ cloudsmith metadata remove your-org/awesome-repo/better-pkg meta-slug
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    remove_args = {
        "metadata": click.style(metadata_slug_perm, bold=True),
        "package": click.style(package, bold=True),
    }

    prompt = (
        "remove the %(metadata)s metadata entry from the %(package)s package"
        % remove_args
    )
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    _echo_action(
        "Removing metadata entry %(metadata)s from the '%(package)s' package ... "
        % remove_args,
        use_stderr,
    )

    context_msg = "Failed to remove metadata from the package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            slug_perm = api_get_package_slug_perm(
                owner=owner, repo=repo, identifier=package
            )
            api_delete_metadata(slug_perm, metadata_slug_perm)

    click.secho("OK", fg="green", err=use_stderr)

    result_payload = {"deleted": True, "slug_perm": metadata_slug_perm}
    if utils.maybe_print_as_json(opts, result_payload):
        return

    click.echo()
    click.secho(
        "Removed metadata entry %(slug)s."
        % {"slug": click.style(metadata_slug_perm, bold=True)}
    )
