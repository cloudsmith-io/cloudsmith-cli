"""CLI/Commands - Push packages."""

# pylint: disable=too-many-lines

import math
import os
import shlex
import time
from datetime import datetime

import click

from ...core import utils as core_utils
from ...core.api.exceptions import ApiException
from ...core.api.files import (
    CHUNK_SIZE,
    multi_part_upload_file,
    request_file_upload,
    upload_file as api_upload_file,
    validate_request_file_upload,
)
from ...core.api.metadata import (
    create_metadata as api_create_metadata,
    validate_metadata as api_validate_metadata,
)
from ...core.api.packages import (
    create_package as api_create_package,
    get_package_formats,
    get_package_status,
    validate_create_package as api_validate_create_package,
)
from .. import command, decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..metadata_common import (
    MetadataContentError,
    ResolvedMetadata,
    attach_metadata_options,
    default_metadata_source_identity,
    require_metadata_content_type,
    resolve_metadata_content,
    source_label_for,
)
from ..types import ExpandPath
from ..utils import maybe_spinner
from .main import main

#: Env var that lets CI/CD wrappers (e.g. GHA) opt out of hard-failing the
#: push when push-time metadata attachment fails. Defaults to ``error`` so an
#: invalid metadata content aborts the upload (design requirement: metadata
#: pushes must surface failures by default). Set to ``0`` or ``warn`` to
#: downgrade failures to a warning and let the package upload regardless.
#: Equivalent settings exist as a CLI flag (``--on-metadata-failure``) and a
#: ``metadata_failure_mode`` key in ``config.ini``; precedence at resolution
#: time is flag > env > config > default.
METADATA_FAILURE_MODE_ENV = "CLOUDSMITH_METADATA_FAILURE_MODE"
METADATA_FAILURE_MODE_WARN = {"0", "warn"}
#: Click option dest names for the push-time metadata flags. Used by the
#: push handler to split metadata flags off from the package-create payload
#: kwargs (the API client would otherwise reject the unknown keys).
METADATA_KWARG_NAMES = (
    "metadata_content_file",
    "metadata_content",
    "metadata_content_type",
    "metadata_source_identity",
)
#: Click dest name for ``--on-metadata-failure``. Popped off the push kwargs
#: separately from the metadata payload kwargs so it does not leak into the
#: package-create API call.
METADATA_FAILURE_MODE_KWARG = "cli_metadata_failure_mode"


def _metadata_failure_is_warn(opts=None):
    """Return True iff metadata failures should be downgraded to a warning.

    Single source of truth for the failure-mode lookup so the validation and
    attach paths cannot drift. Resolves in precedence order:

    1. ``--on-metadata-failure`` flag (``opts.cli_metadata_failure_mode``)
    2. ``$CLOUDSMITH_METADATA_FAILURE_MODE`` env var
    3. ``metadata_failure_mode`` config key (``opts.metadata_failure_mode``)
    4. Default — ``error``

    ``opts`` is optional so direct callers without a CLI context (legacy
    tests) keep working on the env-var path.
    """
    candidates = (
        getattr(opts, "cli_metadata_failure_mode", None) if opts is not None else None,
        os.environ.get(METADATA_FAILURE_MODE_ENV),
        getattr(opts, "metadata_failure_mode", None) if opts is not None else None,
    )
    for value in candidates:
        if value is None:
            continue
        return str(value).strip().lower() in METADATA_FAILURE_MODE_WARN
    return False


def _metadata_content_failure_info(exc):
    info = {
        "status": "content_invalid",
        "error": str(exc),
    }
    if getattr(exc, "source_label", None):
        info["source"] = exc.source_label
    return info


def _warn_metadata_failure(failure_info):
    click.secho(
        "Metadata content is invalid: %(error)s" % failure_info,
        fg="yellow",
        err=True,
    )
    click.secho(
        "Package upload will continue without metadata. Pass "
        "``--on-metadata-failure error`` (or set the "
        f"``metadata_failure_mode`` config key / ``${METADATA_FAILURE_MODE_ENV}`` "
        "env var to ``error``) to fail the push instead.",
        fg="yellow",
        err=True,
    )


def resolve_push_metadata_options(
    *,
    metadata_content_file=None,
    metadata_content=None,
    metadata_content_type=None,
    metadata_source_identity=None,
    opts=None,
):
    """Resolve push-time metadata flags once before package upload loops."""
    if metadata_content_file is not None and metadata_content is not None:
        raise click.UsageError(
            "--metadata-content-file and --metadata-content are mutually exclusive."
        )

    metadata_provided = (
        metadata_content_file is not None or metadata_content is not None
    )
    if not metadata_provided:
        if metadata_content_type or metadata_source_identity:
            raise click.UsageError(
                "Add --metadata-content-file or --metadata-content when using "
                "--metadata-content-type or --metadata-source-identity."
            )
        return ResolvedMetadata(provided=False, content=None), None

    require_metadata_content_type(
        content_type=metadata_content_type,
        content_provided=True,
        option_name="--metadata-content-type",
    )

    try:
        metadata = resolve_metadata_content(
            content_file=metadata_content_file,
            inline_content=metadata_content,
            required=True,
            file_option_name="--metadata-content-file",
            content_option_name="--metadata-content",
        )
    except MetadataContentError as exc:
        if not _metadata_failure_is_warn(opts):
            raise

        source_label = exc.source_label or source_label_for(metadata_content_file)
        metadata = ResolvedMetadata(
            provided=True,
            content=None,
            content_type=metadata_content_type,
            source_identity=(
                metadata_source_identity or default_metadata_source_identity()
            ),
            content_file=metadata_content_file,
            source_label=source_label,
        )
        return metadata, _metadata_content_failure_info(exc)

    return (
        attach_metadata_options(
            metadata,
            content_type=metadata_content_type,
            source_identity=metadata_source_identity,
        ),
        None,
    )


def _handle_metadata_api_exception(ctx, opts, exc, context_msg, skip_errors=False):
    """Route metadata API failures through the standard API exception handler."""
    with handle_api_exceptions(
        ctx,
        opts=opts,
        context_msg=context_msg,
        reraise_on_error=skip_errors,
    ):
        raise exc


def _print_metadata_retry_hint(
    opts,
    owner,
    repo,
    slug,
    metadata_content_file,
    cli_content_type,
    cli_source_identity,
    reason="attach_failed",
):
    """Print a copy-paste ``cloudsmith metadata add`` line for failed attaches.

    Skipped in JSON output mode — the envelope already carries slugs and
    failure context, so CI can reconstruct the command without text parsing.
    Skipped for inline ``--metadata-content`` payloads, since they are not
    safely reproducible as a single shell line (multi-line / quoting / size).

    ``reason`` distinguishes a transient/policy attach failure (``"attach_failed"``,
    where retrying the same payload may succeed) from a pre-validation
    failure (``"validation_failed"``, where the payload itself is broken and
    must be fixed first). Wording changes accordingly.
    """
    if utils.should_use_stderr(opts):
        return
    # Skip when no file path (inline ``--metadata-content``) or stdin ("-"),
    # since neither is reproducible as a single shell line.
    if not metadata_content_file or metadata_content_file == "-":
        return

    parts = [
        f"cloudsmith metadata add {shlex.quote(f'{owner}/{repo}/{slug}')}",
        f"    --file {shlex.quote(metadata_content_file)}",
    ]
    if cli_source_identity:
        parts.append(f"    --source-identity {shlex.quote(cli_source_identity)}")
    if cli_content_type:
        parts.append(f"    --content-type {shlex.quote(cli_content_type)}")

    if reason == "validation_failed":
        heading = "Fix the metadata content, then run:"
    else:
        heading = "Run this command to attach metadata:"

    click.echo(err=True)
    click.secho(heading, fg="yellow", err=True)
    click.secho(" \\\n".join(parts), fg="yellow", err=True)


def validate_metadata_payload(
    ctx,
    opts,
    content,
    content_type,
    source=None,
    skip_errors=False,
):
    """Validate metadata against ``POST /v2/metadata/validate/`` pre-upload.

    Runs before any file upload so a malformed payload does not produce an
    orphan package. Returns ``None`` on success. Routes validation failure
    through ``handle_api_exceptions`` by default so the push aborts before
    any S3 traffic.
    When ``$CLOUDSMITH_METADATA_FAILURE_MODE`` is ``warn``/``0`` it returns a
    metadata-info dict instead so the caller can skip attachment but continue
    the push.

    ``source`` is a human-readable label for the payload origin (file
    basename, ``"stdin"``, ``"inline"``) — surfaced in the progress line so
    users know which source is being validated.
    """
    # pylint: disable=too-many-arguments
    use_stderr = utils.should_use_stderr(opts)

    if source:
        message = "Validating metadata content from {source} ... ".format(
            source=click.style(source, bold=True),
        )
    else:
        message = "Validating metadata content ... "

    click.echo(
        message,
        nl=False,
        err=use_stderr,
    )

    try:
        with maybe_spinner(opts):
            api_validate_metadata(content=content, content_type=content_type)
    except ApiException as exc:
        http_status = getattr(exc, "status", None)
        detail = (
            getattr(exc, "detail", None)
            or getattr(exc, "status_description", None)
            or str(exc)
            or "unknown error"
        )

        click.secho("FAILED", fg="red", err=use_stderr)

        if http_status is not None:
            message = (
                f"Metadata content failed validation (HTTP {http_status}): {detail}"
            )
        else:
            message = f"Metadata content failed validation: {detail}"
        failure_info = {
            "status": "validation_failed",
            "http_status": http_status,
            "error": detail,
        }

        if not _metadata_failure_is_warn(opts):
            opts.push_metadata_info = failure_info
            _handle_metadata_api_exception(
                ctx,
                opts,
                exc,
                context_msg=message,
                skip_errors=skip_errors,
            )

        click.secho(message, fg="yellow", err=True)
        click.secho(
            "Package upload will continue without metadata. Pass "
            "``--on-metadata-failure error`` (or set the "
            f"``metadata_failure_mode`` config key / ``${METADATA_FAILURE_MODE_ENV}`` "
            "env var to ``error``) to fail the push instead.",
            fg="yellow",
            err=True,
        )
        return failure_info

    click.secho("OK", fg="green", err=use_stderr)
    return None


def attach_metadata_to_package(
    ctx,
    opts,
    owner,
    repo,
    slug,
    slug_perm,
    content,
    content_type,
    source_identity,
    skip_errors=False,
    metadata_content_file=None,
    cli_content_type=None,
    cli_source_identity=None,
):
    """Attach a metadata entry to a freshly-created package.

    Failure is fatal by default: the API error is reported and the push
    exits non-zero so CI/CD pipelines surface broken SBOM/BuildInfo uploads
    instead of silently shipping a package without metadata. Wrappers that
    explicitly want the legacy non-fatal behaviour can set
    ``$CLOUDSMITH_METADATA_FAILURE_MODE`` to ``warn`` (or ``0``).
    """
    # pylint: disable=too-many-arguments
    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Attaching metadata to package %(slug)s ... "
        % {"slug": click.style(slug_perm, bold=True)},
        nl=False,
        err=use_stderr,
    )

    try:
        with maybe_spinner(opts):
            entry = api_create_metadata(
                slug_perm,
                content=content,
                content_type=content_type,
                source_identity=source_identity,
            )
    except ApiException as exc:
        click.secho("FAILED", fg="red", err=use_stderr)

        http_status = getattr(exc, "status", None)
        detail = (
            getattr(exc, "detail", None)
            or getattr(exc, "status_description", None)
            or str(exc)
            or "unknown error"
        )
        if http_status is not None:
            message = (
                f"Could not attach metadata to package {slug_perm} "
                f"(HTTP {http_status}): {detail}"
            )
        else:
            message = f"Could not attach metadata to package {slug_perm}: {detail}"
        failure_info = {
            "status": "attach_failed",
            "http_status": http_status,
            "error": detail,
        }

        hint_kwargs = {
            "opts": opts,
            "owner": owner,
            "repo": repo,
            "slug": slug,
            "metadata_content_file": metadata_content_file,
            "cli_content_type": cli_content_type,
            "cli_source_identity": cli_source_identity,
        }

        if not _metadata_failure_is_warn(opts):
            opts.push_metadata_info = failure_info
            _print_metadata_retry_hint(**hint_kwargs)
            _handle_metadata_api_exception(
                ctx,
                opts,
                exc,
                context_msg=message,
                skip_errors=skip_errors,
            )

        click.secho(message, fg="yellow", err=True)
        click.secho(
            "Package upload completed without metadata. Pass "
            "``--on-metadata-failure error`` (or set the "
            f"``metadata_failure_mode`` config key / ``${METADATA_FAILURE_MODE_ENV}`` "
            "env var to ``error``) to fail the push instead.",
            fg="yellow",
            err=True,
        )
        _print_metadata_retry_hint(**hint_kwargs)
        return failure_info

    click.secho("OK", fg="green", err=use_stderr)

    metadata_slug_perm = (entry or {}).get("slug_perm") or "?"
    package_path = "{owner}/{repo}/{slug}".format(
        owner=click.style(owner, fg="magenta"),
        repo=click.style(repo, fg="magenta"),
        slug=click.style(slug, fg="green"),
    )
    click.echo(
        "Metadata attached: %(path)s/%(metadata)s"
        % {
            "path": package_path,
            "metadata": click.style(metadata_slug_perm, bold=True),
        },
        err=use_stderr,
    )

    return {
        "status": "attached",
        "slug_perm": (entry or {}).get("slug_perm"),
        "entry": entry or None,
    }


def validate_upload_file(ctx, opts, owner, repo, filepath, skip_errors):
    """Validate parameters for requesting a file upload."""
    filename = click.format_filename(filepath)
    basename = os.path.basename(filename)

    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Checking %(filename)s file upload parameters ... "
        % {"filename": click.style(basename, bold=True)},
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to validate upload parameters!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            md5_checksum = validate_request_file_upload(
                owner=owner, repo=repo, filepath=filename
            )

    click.secho("OK", fg="green", err=use_stderr)

    return md5_checksum


def upload_file(ctx, opts, owner, repo, filepath, skip_errors, md5_checksum):
    """Upload a package file via the API."""
    filename = click.format_filename(filepath)
    basename = os.path.basename(filename)

    filesize = core_utils.get_file_size(filepath=filename)
    projected_chunks = math.floor(filesize / CHUNK_SIZE) + 1
    is_multi_part_upload = projected_chunks > 1

    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Requesting file upload for %(filename)s ... "
        % {"filename": click.style(basename, bold=True)},
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to request file upload!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            identifier, upload_url, upload_fields = request_file_upload(
                owner=owner,
                repo=repo,
                filepath=filename,
                md5_checksum=md5_checksum,
                is_multi_part_upload=is_multi_part_upload,
            )

    click.secho("OK", fg="green", err=use_stderr)

    context_msg = "Failed to upload file!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        label = f"Uploading {click.style(basename, bold=True)}:"

        if not is_multi_part_upload:
            if use_stderr:
                api_upload_file(
                    upload_url=upload_url,
                    upload_fields=upload_fields,
                    filepath=filename,
                )
            else:
                # We can upload the whole file in one go.
                with click.progressbar(
                    length=filesize,
                    label=label,
                    fill_char=click.style("#", fg="green"),
                    empty_char=click.style("-", fg="red"),
                ) as pb:

                    def progress_callback(monitor):
                        pb.update(monitor.bytes_read)

                    api_upload_file(
                        upload_url=upload_url,
                        upload_fields=upload_fields,
                        filepath=filename,
                        callback=progress_callback,
                    )
        else:
            if use_stderr:
                multi_part_upload_file(
                    opts=opts,
                    upload_url=upload_url,
                    owner=owner,
                    repo=repo,
                    filepath=filename,
                    upload_id=identifier,
                    callback=lambda: None,
                )
            else:
                # The file is sufficiently large that we need to upload in chunks.
                with click.progressbar(
                    length=projected_chunks,
                    label=label,
                    fill_char=click.style("#", fg="green"),
                    empty_char=click.style("-", fg="red"),
                ) as pb:

                    def progress_callback():
                        pb.update(1)

                    multi_part_upload_file(
                        opts=opts,
                        upload_url=upload_url,
                        owner=owner,
                        repo=repo,
                        filepath=filename,
                        callback=progress_callback,
                        upload_id=identifier,
                    )

    return identifier


def validate_create_package(
    ctx, opts, owner, repo, package_type, skip_errors, **kwargs
):
    """Check new package parameters via the API."""
    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Checking %(package_type)s package upload parameters ... "
        % {"package_type": click.style(package_type, bold=True)},
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to validate upload parameters!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            api_validate_create_package(
                package_format=package_type, owner=owner, repo=repo, **kwargs
            )

    click.secho("OK", fg="green", err=use_stderr)
    return True


def create_package(ctx, opts, owner, repo, package_type, skip_errors, **kwargs):
    """Create a new package via the API."""
    use_stderr = utils.should_use_stderr(opts)

    click.echo(
        "Creating a new %(package_type)s package ... "
        % {"package_type": click.style(package_type, bold=True)},
        nl=False,
        err=use_stderr,
    )

    context_msg = "Failed to create package!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            slug_perm, slug = api_create_package(
                package_format=package_type, owner=owner, repo=repo, **kwargs
            )

    click.secho("OK", fg="green", err=use_stderr)

    click.echo(
        "Created: %(owner)s/%(repo)s/%(slug)s (%(slug_perm)s)"
        % {
            "owner": click.style(owner, fg="magenta"),
            "repo": click.style(repo, fg="magenta"),
            "slug": click.style(slug, fg="green"),
            "slug_perm": click.style(slug_perm, bold=True),
        },
        err=use_stderr,
    )

    return slug_perm, slug


def wait_for_package_sync(
    ctx, opts, owner, repo, slug, wait_interval, skip_errors, attempts=3
):
    """Wait for a package to synchronise (or fail)."""
    # pylint: disable=too-many-locals
    use_stderr = utils.should_use_stderr(opts)

    attempts -= 1
    click.echo(err=use_stderr)
    label = f"Synchronising {click.style(slug, fg='green')}:"

    status_str = "Waiting"
    stage_str = None

    def display_status(current):
        """Display current sync status."""
        # pylint: disable=unused-argument
        if not stage_str or "Unknown" in stage_str:
            return status_str
        return click.style(
            f"{status_str} / {stage_str}",
            fg="cyan",
        )

    start = datetime.now()
    context_msg = "Failed to synchronise file!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        left = 100
        last_progress = 0
        total_wait_interval = max(1.0, wait_interval)
        first = True

        if use_stderr:
            # When using stderr for logs, avoid an interactive progress bar and just poll for status.
            while True:
                res = get_package_status(owner, repo, slug)
                ok, failed, _, _, _, _ = res
                if ok or failed:
                    break

                # Sleep if we are going to loop again
                if not first:
                    time.sleep(total_wait_interval)
                    total_wait_interval = min(
                        300.0, total_wait_interval + wait_interval
                    )
                first = False

        else:
            with click.progressbar(
                length=left,
                label=label,
                fill_char=click.style("#", fg="green"),
                empty_char=click.style("-", fg="red"),
                item_show_func=display_status,
            ) as pb:
                while True:
                    res = get_package_status(owner, repo, slug)
                    ok, failed, progress, status_str, stage_str, reason = res
                    progress = max(1, progress)
                    delta = progress - last_progress
                    pb.update(delta)
                    if delta > 0:
                        last_progress = progress
                        left -= delta
                    if ok or failed:
                        break
                    if first:
                        first = False
                    else:
                        # Sleep, but only after the first status call
                        time.sleep(total_wait_interval)
                        total_wait_interval = min(
                            300.0, total_wait_interval + wait_interval
                        )

                if left > 0:
                    pb.update(left)

    end = datetime.now()
    seconds = (end - start).total_seconds()

    click.echo(err=use_stderr)

    if ok:
        click.secho(
            "Package synchronised successfully in %(seconds)s second(s)!"
            % {"seconds": click.style(str(seconds), bold=True)},
            fg="green",
            err=use_stderr,
        )
        return

    click.secho(
        "Package failed to synchronise in %(seconds)s during stage: %(stage)s"
        % {
            "seconds": click.style(str(seconds), bold=True),
            "stage": click.style(stage_str or "Unknown", fg="yellow"),
        },
        fg="red",
        err=use_stderr,
    )

    if reason:
        click.secho(
            f"Reason given: {click.style(reason, fg='yellow')}",
            fg="red",
            err=use_stderr,
        )

        # pylint: disable=fixme
        # FIXME: The API should communicate "no retry" fails
        if "package should be deleted" in reason and attempts > 1:
            click.secho(
                "This is not recoverable, so stopping further attempts!",
                fg="red",
                err=use_stderr,
            )
            click.echo(err=use_stderr)
            attempts = 0

    if attempts + 1 > 0:
        # Show attempts upto and including zero attempts left
        click.secho(
            "Attempts left: %(left)s (%(action)s)"
            % {
                "left": click.style(str(attempts), bold=True),
                "action": "trying again" if attempts > 0 else "giving up",
            },
            err=use_stderr,
        )
        click.echo(err=use_stderr)

    if attempts > 0:
        from .resync import resync_package

        resync_package(
            ctx=ctx,
            opts=opts,
            owner=owner,
            repo=repo,
            slug=slug,
            skip_errors=skip_errors,
        )

        wait_for_package_sync(
            ctx=ctx,
            opts=opts,
            owner=owner,
            repo=repo,
            slug=slug,
            wait_interval=wait_interval,
            skip_errors=skip_errors,
            attempts=attempts,
        )
    else:
        ctx.exit(1)


def upload_files_and_create_package(
    ctx,
    opts,
    package_type,
    owner_repo,
    dry_run,
    no_wait_for_sync,
    wait_interval,
    skip_errors,
    sync_attempts,
    metadata_content_file=None,
    metadata_content=None,
    metadata_content_type=None,
    metadata_source_identity=None,
    metadata=None,
    metadata_failure_info=None,
    **kwargs,
):
    """Upload package files and create a new package."""
    # pylint: disable=unused-argument,too-many-arguments,too-many-locals
    owner, repo = owner_repo

    # Reset push-time metadata state for this call. ``handle_api_exceptions``
    # consults this attribute to surface validation/attach context in the
    # JSON error envelope; an unset value would leak prior state on retries.
    opts.push_metadata_info = None

    # 0. Resolve push-time metadata before package work. The dynamic command
    # handler resolves once for multi-file pushes so stdin is consumed once;
    # direct callers can still pass the metadata flags for test coverage.
    if metadata is None:
        metadata, metadata_failure_info = resolve_push_metadata_options(
            metadata_content_file=metadata_content_file,
            metadata_content=metadata_content,
            metadata_content_type=metadata_content_type,
            metadata_source_identity=metadata_source_identity,
            opts=opts,
        )

    should_attach_metadata = metadata.provided and metadata_failure_info is None

    # Publish a warn-mode resolve failure on ``opts`` BEFORE the package
    # validation call so the JSON error envelope still carries the metadata
    # context if ``validate_create_package`` aborts the push (e.g. typo in
    # --name/--version, bad repo, auth failure).
    if metadata_failure_info is not None:
        opts.push_metadata_info = metadata_failure_info
        _warn_metadata_failure(metadata_failure_info)

    # 1. Validate package create parameters. This runs before the metadata
    #    pre-validation so a typo in --name/--version fails fast without
    #    burning a /v2/metadata/validate/ round-trip first.
    validate_create_package(
        ctx=ctx,
        opts=opts,
        owner=owner,
        repo=repo,
        package_type=package_type,
        skip_errors=skip_errors,
        **kwargs,
    )

    # 1b. Pre-validate metadata against the server-side schema endpoint so a
    #     malformed payload cannot produce an orphan package (the upload would
    #     succeed and only the attach would fail).
    if metadata_failure_info is None and should_attach_metadata:
        validation_failure = validate_metadata_payload(
            ctx=ctx,
            opts=opts,
            content=metadata.content,
            content_type=metadata.content_type,
            source=metadata.source_label,
            skip_errors=skip_errors,
        )
        if validation_failure is not None:
            # Warn-mode validation failure: keep the push, drop the attach.
            should_attach_metadata = False
            opts.push_metadata_info = validation_failure

    # 2. Validate file upload parameters
    md5_checksums = {}
    for k, v in kwargs.items():
        if not v:
            continue

        # Handle a single file
        if k.endswith("_file"):
            md5_checksums[k] = validate_upload_file(
                ctx=ctx,
                opts=opts,
                owner=owner,
                repo=repo,
                filepath=v,
                skip_errors=skip_errors,
            )

        # Check if the key is "extra_files" (to handle multiple files)
        if k == "extra_files" and isinstance(v, list):
            md5_checksums[k] = [
                validate_upload_file(
                    ctx=ctx,
                    opts=opts,
                    owner=owner,
                    repo=repo,
                    filepath=file,
                    skip_errors=skip_errors,
                )
                for file in v
            ]

    if dry_run:
        click.echo()
        click.secho("You requested a dry run so skipping upload.", fg="yellow")
        return

    # 3. Upload any arguments that look like files
    for k, v in kwargs.items():
        if not v:
            continue

        # Handle a single file
        if k.endswith("_file"):
            kwargs[k] = upload_file(
                ctx=ctx,
                opts=opts,
                owner=owner,
                repo=repo,
                filepath=v,
                skip_errors=skip_errors,
                md5_checksum=md5_checksums[k],
            )

        # Check if the key is "extra_files" (to handle multiple files)
        if k == "extra_files" and isinstance(v, list):
            kwargs[k] = [
                upload_file(
                    ctx=ctx,
                    opts=opts,
                    owner=owner,
                    repo=repo,
                    filepath=file,
                    skip_errors=skip_errors,
                    md5_checksum=md5_checksums[k][idx],
                )
                for idx, file in enumerate(v)
            ]

    # 4. Create the package with package files and additional arguments
    slug_perm, slug = create_package(
        ctx=ctx,
        opts=opts,
        owner=owner,
        repo=repo,
        package_type=package_type,
        skip_errors=skip_errors,
        **kwargs,
    )

    # 5. Attach push-time metadata, if provided AND it passed validation.
    #    Warn-mode metadata failures leave opts.push_metadata_info populated
    #    and should_attach_metadata=False; surface a retry hint now that we
    #    have the package slug. Skipped in JSON mode and for inline payloads.
    if should_attach_metadata:
        opts.push_metadata_info = attach_metadata_to_package(
            ctx=ctx,
            opts=opts,
            owner=owner,
            repo=repo,
            slug=slug,
            slug_perm=slug_perm,
            content=metadata.content,
            content_type=metadata.content_type,
            source_identity=metadata.source_identity,
            skip_errors=skip_errors,
            metadata_content_file=metadata.content_file,
            cli_content_type=metadata.content_type,
            cli_source_identity=metadata_source_identity,
        )
    elif metadata.provided:
        # Metadata resolution/validation already warned the user; the payload
        # is broken so a straight retry would fail. Use the "fix first" hint.
        _print_metadata_retry_hint(
            opts=opts,
            owner=owner,
            repo=repo,
            slug=slug,
            metadata_content_file=metadata.content_file,
            cli_content_type=metadata.content_type,
            cli_source_identity=metadata_source_identity,
            reason="validation_failed",
        )

    if no_wait_for_sync:
        return slug_perm, slug

    # 6. (optionally) Wait for the package to synchronise
    wait_for_package_sync(
        ctx=ctx,
        opts=opts,
        owner=owner,
        repo=repo,
        slug=slug,
        wait_interval=wait_interval,
        skip_errors=skip_errors,
        attempts=sync_attempts,
    )

    return slug_perm, slug


def create_push_handlers():  # noqa: C901
    """Create a handler for upload per package format."""
    # pylint: disable=fixme
    # HACK: hacky territory - Dynamically generate a handler for each of the
    # package formats, until we have slightly more clever 'guess type'
    # handling. :-)
    handlers = create_push_handlers.handlers = {}
    context = create_push_handlers.context = get_package_formats()

    for key, parameters in context.items():
        kwargs = parameters.copy()

        # Remove standard arguments
        kwargs.pop("package_file")
        if "distribution" in parameters:
            has_distribution_param = True
            kwargs.pop("distribution")
        else:
            has_distribution_param = False

        has_additional_params = len(kwargs) > 0

        help_text = f"""
            Push/upload a new {key.capitalize()} package upstream.
            """

        if has_additional_params:
            help_text += """

            PACKAGE_FILE: The main file to create the package from.
            """
        else:
            help_text += """

            PACKAGE_FILE: Any number of files to create packages from. Each
            file will result in a separate package.
            """

        if has_distribution_param:
            target_metavar = "OWNER/REPO/DISTRO/RELEASE"
            target_callback = validators.validate_owner_repo_distro
            help_text += """

            OWNER/REPO/DISTRO/RELEASE: Specify the OWNER namespace (i.e.
            user or org), the REPO name where the package file will be uploaded
            to, and the DISTRO and RELEASE the package is for. All separated by
            a slash.

            Example: 'your-org/awesome-repo/ubuntu/xenial'.
            """
        else:
            target_metavar = "OWNER/REPO"
            target_callback = validators.validate_owner_repo
            help_text += """

            OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
            REPO name where the package file will be uploaded to. All separated
            by a slash.

            Example: 'your-org/awesome-repo'.
            """

        @push.command(name=key, help=help_text)
        @decorators.common_cli_config_options
        @decorators.common_cli_output_options
        @decorators.common_package_action_options
        @decorators.common_api_auth_options
        @decorators.initialise_api
        @click.argument("owner_repo", metavar=target_metavar, callback=target_callback)
        @click.argument(
            "package_file",
            nargs=1 if has_additional_params else -1,
            type=ExpandPath(
                dir_okay=False, exists=True, writable=False, resolve_path=True
            ),
        )
        @click.option(
            "-n",
            "--dry-run",
            default=False,
            is_flag=True,
            help="Execute in dry run mode (don't upload anything.)",
        )
        @click.option(
            "--metadata-content-file",
            "metadata_content_file",
            type=click.Path(
                exists=True,
                dir_okay=False,
                readable=True,
                resolve_path=True,
                allow_dash=True,
            ),
            default=None,
            help=(
                "Read metadata content from a JSON file "
                "(for example, SBOM or BuildInfo). Use '-' for stdin. "
                "Content must be a JSON object. "
                "Mutually exclusive with --metadata-content. "
                "Metadata failures abort the push by default; pass "
                "--on-metadata-failure warn (or set the "
                "metadata_failure_mode config key / "
                "$CLOUDSMITH_METADATA_FAILURE_MODE env var to warn) to "
                "downgrade to a warning and keep the package upload."
            ),
        )
        @click.option(
            "--metadata-content",
            "metadata_content",
            default=None,
            help=(
                "Set metadata content from inline JSON. Content must be a "
                "JSON object. "
                "Mutually exclusive with --metadata-content-file. "
                "Metadata failures abort the push by default; pass "
                "--on-metadata-failure warn (or set the "
                "metadata_failure_mode config key / "
                "$CLOUDSMITH_METADATA_FAILURE_MODE env var to warn) to "
                "downgrade to a warning and keep the package upload."
            ),
        )
        @click.option(
            "--metadata-content-type",
            "metadata_content_type",
            default=None,
            help=(
                "Content type for metadata content "
                "(for example, 'application/vnd.jfrog.buildinfo+json'). "
                "Required when metadata content is supplied and determines "
                "the schema used for validation."
            ),
        )
        @click.option(
            "--metadata-source-identity",
            "metadata_source_identity",
            default=None,
            help=(
                "Identifier for the metadata source. "
                "Defaults to 'cloudsmith-cli@<version>'."
            ),
        )
        @click.option(
            "--on-metadata-failure",
            METADATA_FAILURE_MODE_KWARG,
            type=click.Choice(["error", "warn"]),
            default=None,
            help=(
                "How to handle push-time metadata failures. 'error' "
                "(default) aborts the push so CI/CD surfaces broken "
                "SBOM/BuildInfo uploads; 'warn' downgrades to a warning "
                "and lets the package upload regardless. Overrides the "
                "$CLOUDSMITH_METADATA_FAILURE_MODE env var and the "
                "'metadata_failure_mode' config key for this push."
            ),
        )
        @click.pass_context
        def push_handler(ctx, *args, **kwargs):
            """Handle upload for a specific package format."""
            opts = kwargs.get("opts")
            parameters = context.get(ctx.info_name)
            kwargs["package_type"] = ctx.info_name

            owner_repo = kwargs.pop("owner_repo")
            if "distribution" in parameters:
                kwargs["distribution"] = "/".join(owner_repo[2:])
                owner_repo = owner_repo[0:2]
            kwargs["owner_repo"] = owner_repo

            # Metadata flags are not part of the package-create payload, so
            # pop them and forward them as explicit kwargs so they don't leak
            # into validate_create_package() / create_package().
            metadata_kwargs = {
                key: kwargs.pop(key, None) for key in METADATA_KWARG_NAMES
            }

            # ``--on-metadata-failure`` is also not a package-create kwarg;
            # publish it onto opts so the failure-mode helper can prefer it
            # over env/config without an explicit thread through every call.
            cli_failure_mode = kwargs.pop(METADATA_FAILURE_MODE_KWARG, None)
            if cli_failure_mode is not None:
                opts.cli_metadata_failure_mode = cli_failure_mode

            package_files = kwargs.pop("package_file")
            if not isinstance(package_files, tuple):
                package_files = (package_files,)

            # Reject multi-file push combined with metadata flags. A single
            # metadata payload semantically belongs to one package; silently
            # fanning it out across N packages (and validating + attaching it
            # N times) is almost never what the user wants. Force them to
            # push files individually with metadata, or drop the flags.
            metadata_flags_set = any(
                metadata_kwargs.get(k) for k in METADATA_KWARG_NAMES
            )
            if len(package_files) > 1 and metadata_flags_set:
                raise click.UsageError(
                    "Metadata flags (--metadata-content-file, --metadata-content, "
                    "--metadata-content-type, --metadata-source-identity) cannot "
                    "be combined with multiple package files. Push files "
                    "individually when attaching metadata."
                )

            metadata, metadata_failure_info = resolve_push_metadata_options(
                **metadata_kwargs, opts=opts
            )

            results = []
            for package_file in package_files:
                kwargs["package_file"] = package_file

                try:
                    click.echo(err=utils.should_use_stderr(opts))
                    res = upload_files_and_create_package(
                        ctx,
                        *args,
                        **kwargs,
                        **metadata_kwargs,
                        metadata=metadata,
                        metadata_failure_info=metadata_failure_info,
                    )
                    if res:
                        # ``upload_files_and_create_package`` resets and then
                        # populates ``opts.push_metadata_info`` on every call,
                        # so reading it here always reflects this iteration.
                        results.append((res, opts.push_metadata_info))
                except ApiException:
                    click.secho(
                        "Skipping error and moving on.",
                        fg="yellow",
                        err=utils.should_use_stderr(opts),
                    )

                click.echo(err=utils.should_use_stderr(opts))

            if utils.should_use_stderr(opts):
                data = []
                for (slug_perm, slug), metadata_info in results:
                    entry = {
                        "slug_perm": slug_perm,
                        "slug": slug,
                        "status": "OK",  # Assuming success if we got here
                    }
                    if metadata_info is not None:
                        entry["metadata_attachment"] = metadata_info
                    data.append(entry)

                if len(data) == 1:
                    utils.maybe_print_as_json(opts, data[0])
                else:
                    utils.maybe_print_as_json(opts, data)

        # Add any additional arguments
        for k, info in kwargs.items():
            option_kwargs = {}
            option_name_fmt = "--%(key)s"

            if k.endswith("_file"):
                # Treat parameters that end with _file as uploadable filepaths.
                option_kwargs["type"] = ExpandPath(
                    dir_okay=False, exists=True, writable=False, resolve_path=True
                )
            elif k == "extra_files":
                # Handle multiple files for extra_files parameter.
                option_kwargs["type"] = str
                option_kwargs["multiple"] = True
                option_kwargs["callback"] = validators.validate_extra_files_parameter
                info["help"] = (
                    info["help"] + " Accepts a comma-separated list of values."
                )
            elif info["type"] == "bool":
                option_name_fmt = "--%(key)s/--no-%(key)s"
                option_kwargs["is_flag"] = True
            else:
                option_kwargs["type"] = str

            if k == "republish":
                # None is required to default upload republish settings to the repo republish settings
                option_kwargs["default"] = None

            option_name = option_name_fmt % {"key": k.replace("_", "-")}
            decorator = click.option(
                option_name,
                required=info["required"],
                help=info["help"],
                **option_kwargs,
            )
            push_handler = decorator(push_handler)

        handlers[key] = push_handler


@main.group(cls=command.AliasGroup, aliases=["upload", "deploy"])
@click.pass_context
def push(ctx):  # pylint: disable=unused-argument
    """
    Push (upload) a new package to a repository.

    At the moment you need to specify the package format (see below) of
    the package you're uploading. Each package format may have additional
    options/parameters that are specific to that package format (e.g. the
    Maven backend has the concepts of artifact and group IDs).
    """


create_push_handlers()
