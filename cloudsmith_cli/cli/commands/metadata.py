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
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..metadata_common import (
    attach_metadata_options,
    require_metadata_content_type,
    resolve_metadata_content,
)
from ..utils import maybe_spinner
from .main import main

_METADATA_HEADERS = [
    "Slug",
    "Content type",
    "Classification",
    "Source kind",
    "Source identity",
]


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
    if utils.maybe_print_as_json(
        opts, list(entries), page_info=None if page_all else page_info
    ):
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
    list_suffix = f"metadata entr{'ies' if num_results != 1 else 'y'}"
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


@main.group(name="metadata", cls=command.AliasGroup)
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def metadata_(ctx, opts):  # pylint: disable=unused-argument
    """
    Manage package metadata.
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
        "Filter by source kind. Accepts an integer or name "
        "(for example, 'customer' or 'third_party'). Ignored when "
        "METADATA_SLUG_PERM is given."
    ),
)
@click.option(
    "--classification",
    "classification",
    default=None,
    help=(
        "Filter by classification. Accepts an integer or name "
        "(for example, 'provenance' or 'sbom'). Ignored when "
        "METADATA_SLUG_PERM is given."
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
    List package metadata.

    OWNER/REPO/PACKAGE: target package.

    METADATA_SLUG_PERM (optional): fetch one metadata entry. Pagination and
    filters are ignored.

    \b
    Examples:
      $ cloudsmith metadata list example-org/example-repo/example-pkg
      $ cloudsmith metadata list example-org/example-repo/example-pkg --classification provenance
      $ cloudsmith metadata list example-org/example-repo/example-pkg meta-slug-perm
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    if metadata_slug_perm:
        _echo_action(
            "Fetching metadata %(metadata)s for %(package)s ... "
            % {
                "metadata": click.style(metadata_slug_perm, bold=True),
                "package": click.style(package, bold=True),
            },
            use_stderr,
        )

        context_msg = "Could not fetch package metadata."
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
        "Listing metadata for %(package)s ... "
        % {"package": click.style(package, bold=True)},
        use_stderr,
    )

    context_msg = "Could not list package metadata."
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
        "Content type for metadata content (for example, 'application/json'). "
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
    help="Read metadata content from a JSON file. Use '-' for stdin.",
)
@click.option(
    "--content",
    "inline_content",
    default=None,
    help="Set metadata content from inline JSON. Cannot be used with --file.",
)
@click.option(
    "--source-identity",
    "source_identity",
    default=None,
    help=(
        "Identifier for the metadata source. " "Defaults to 'cloudsmith-cli@<version>'."
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
    Attach metadata to a package.

    OWNER/REPO/PACKAGE: target package.

    Exactly one of --file or --content must be provided.
    Content type is set on creation and cannot be changed.

    \b
    Examples:
      $ cloudsmith metadata add example-org/example-repo/example-pkg \\
            --content-type application/json \\
            --content '{"foo": "bar"}'
      $ cat metadata.json | cloudsmith metadata add example-org/example-repo/example-pkg \\
            --content-type application/json \\
            --file -
      $ cloudsmith metadata add example-org/example-repo/example-pkg \\
            --content-type application/vnd.jfrog.buildinfo+json \\
            --file buildinfo.json
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    metadata = resolve_metadata_content(
        content_file=content_file,
        inline_content=inline_content,
        required=True,
        file_option_name="--file",
        content_option_name="--content",
    )
    require_metadata_content_type(
        content_type=content_type,
        content_provided=metadata.provided,
        option_name="--content-type",
    )
    metadata = attach_metadata_options(
        metadata,
        content_type=content_type,
        source_identity=source_identity,
    )

    _echo_action(
        "Attaching metadata to %(package)s ... "
        % {"package": click.style(package, bold=True)},
        use_stderr,
    )

    context_msg = "Could not attach metadata."
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            slug_perm = api_get_package_slug_perm(
                owner=owner, repo=repo, identifier=package
            )
            entry = api_create_metadata(
                slug_perm,
                content=metadata.content,
                content_type=metadata.content_type,
                source_identity=metadata.source_identity,
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
    help="Read replacement metadata content from a JSON file. Use '-' for stdin.",
)
@click.option(
    "--content",
    "inline_content",
    default=None,
    help=(
        "Set replacement metadata content from inline JSON. Cannot be used with "
        "--file."
    ),
)
@click.option(
    "--source-identity",
    "source_identity",
    default=None,
    help="Update the metadata source identity.",
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
    Update package metadata.

    OWNER/REPO/PACKAGE: target package.
    METADATA_SLUG_PERM: permanent slug for the metadata entry.

    Content type cannot be changed after creation.

    \b
    Examples:
      $ cloudsmith metadata update example-org/example-repo/example-pkg meta-slug \\
            --content '{"foo": "baz"}'
      $ cat metadata.json | cloudsmith metadata update example-org/example-repo/example-pkg meta-slug \\
            --file -
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    metadata = resolve_metadata_content(
        content_file=content_file,
        inline_content=inline_content,
        required=False,
        file_option_name="--file",
        content_option_name="--content",
    )

    patch_kwargs = {}
    if metadata.provided:
        patch_kwargs["content"] = metadata.content
    if source_identity is not None:
        patch_kwargs["source_identity"] = source_identity
    if not patch_kwargs:
        raise click.UsageError(
            "Nothing to update. Provide --file, --content, or --source-identity."
        )

    _echo_action(
        "Updating metadata %(metadata)s for %(package)s ... "
        % {
            "metadata": click.style(metadata_slug_perm, bold=True),
            "package": click.style(package, bold=True),
        },
        use_stderr,
    )

    context_msg = "Could not update package metadata."
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
    help="Skip confirmation prompt.",
)
@click.pass_context
def remove_metadata(ctx, opts, owner_repo_package, metadata_slug_perm, yes):
    """
    Remove package metadata.

    OWNER/REPO/PACKAGE: target package.
    METADATA_SLUG_PERM: permanent slug for the metadata entry.

    \b
    Example:
      $ cloudsmith metadata remove example-org/example-repo/example-pkg meta-slug
    """
    owner, repo, package = owner_repo_package
    use_stderr = utils.should_use_stderr(opts)

    remove_args = {
        "metadata": click.style(metadata_slug_perm, bold=True),
        "package": click.style(package, bold=True),
    }

    prompt = "remove metadata %(metadata)s from package %(package)s" % remove_args
    if not utils.confirm_operation(prompt, assume_yes=yes, err=use_stderr):
        return

    _echo_action(
        "Removing metadata %(metadata)s from %(package)s ... " % remove_args,
        use_stderr,
    )

    context_msg = "Could not remove package metadata."
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
        "Metadata removed: %(slug)s."
        % {"slug": click.style(metadata_slug_perm, bold=True)}
    )
