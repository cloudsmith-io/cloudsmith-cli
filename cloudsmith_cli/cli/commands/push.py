# -*- coding: utf-8 -*-
"""CLI/Commands - Push packages."""
from __future__ import absolute_import, print_function, unicode_literals

import os
import time

import click
import six

from ...core import utils
from ...core.api.exceptions import ApiException
from ...core.api.files import (
    request_file_upload,
    upload_file as api_upload_file,
    validate_request_file_upload,
)
from ...core.api.packages import (
    create_package as api_create_package,
    get_package_formats,
    get_package_status,
    validate_create_package as api_validate_create_package,
)
from .. import command, decorators, validators
from ..exceptions import handle_api_exceptions
from ..types import ExpandPath
from ..utils import maybe_spinner
from .main import main


def validate_upload_file(ctx, opts, owner, repo, filepath, skip_errors):
    """Validate parameters for requesting a file upload."""
    filename = click.format_filename(filepath)
    basename = os.path.basename(filename)

    click.echo(
        "Checking %(filename)s file upload parameters ... "
        % {"filename": click.style(basename, bold=True)},
        nl=False,
    )

    context_msg = "Failed to validate upload parameters!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            md5_checksum = validate_request_file_upload(
                owner=owner, repo=repo, filepath=filename
            )

    click.secho("OK", fg="green")

    return md5_checksum


def upload_file(ctx, opts, owner, repo, filepath, skip_errors, md5_checksum):
    """Upload a package file via the API."""
    filename = click.format_filename(filepath)
    basename = os.path.basename(filename)

    click.echo(
        "Requesting file upload for %(filename)s ... "
        % {"filename": click.style(basename, bold=True)},
        nl=False,
    )

    context_msg = "Failed to request file upload!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            identifier, upload_url, upload_fields = request_file_upload(
                owner=owner, repo=repo, filepath=filename, md5_checksum=md5_checksum
            )

    click.secho("OK", fg="green")

    context_msg = "Failed to upload file!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        filesize = utils.get_file_size(filepath=filename)

        label = "Uploading %(filename)s:" % {
            "filename": click.style(basename, bold=True)
        }

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

    return identifier


def validate_create_package(
    ctx, opts, owner, repo, package_type, skip_errors, **kwargs
):
    """Check new package parameters via the API."""
    click.echo(
        "Checking %(package_type)s package upload parameters ... "
        % {"package_type": click.style(package_type, bold=True)},
        nl=False,
    )

    context_msg = "Failed to validate upload parameters!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            api_validate_create_package(
                package_format=package_type, owner=owner, repo=repo, **kwargs
            )

    click.secho("OK", fg="green")
    return True


def create_package(ctx, opts, owner, repo, package_type, skip_errors, **kwargs):
    """Create a new package via the API."""
    click.echo(
        "Creating a new %(package_type)s package ... "
        % {"package_type": click.style(package_type, bold=True)},
        nl=False,
    )

    context_msg = "Failed to create package!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        with maybe_spinner(opts):
            slug_perm, slug = api_create_package(
                package_format=package_type, owner=owner, repo=repo, **kwargs
            )

    click.secho("OK", fg="green")

    click.echo(
        "Created: %(owner)s/%(repo)s/%(slug)s (%(slug_perm)s)"
        % {
            "owner": click.style(owner, fg="magenta"),
            "repo": click.style(repo, fg="magenta"),
            "slug": click.style(slug, fg="green"),
            "slug_perm": click.style(slug_perm, bold=True),
        }
    )

    return slug_perm, slug


def wait_for_package_sync(
    ctx, opts, owner, repo, slug, wait_interval, skip_errors, attempts=3
):
    """Wait for a package to synchronise (or fail)."""
    # pylint: disable=too-many-locals
    attempts -= 1
    click.echo()
    label = "Synchronising %(package)s:" % {"package": click.style(slug, fg="green")}

    status_str = "Waiting"
    stage_str = None

    def display_status(current):
        """Display current sync status."""
        # pylint: disable=unused-argument
        if not stage_str:
            return status_str
        return click.style(
            "%(status)s / %(stage)s" % {"status": status_str, "stage": stage_str},
            fg="cyan",
        )

    context_msg = "Failed to synchronise file!"
    with handle_api_exceptions(
        ctx, opts=opts, context_msg=context_msg, reraise_on_error=skip_errors
    ):
        last_progress = 0
        with click.progressbar(
            length=100,
            label=label,
            fill_char=click.style("#", fg="green"),
            empty_char=click.style("-", fg="red"),
            item_show_func=display_status,
        ) as pb:
            while True:
                res = get_package_status(owner, repo, slug)
                ok, failed, progress, status_str, stage_str, reason = res
                delta = progress - last_progress
                if delta > 0:
                    last_progress = progress
                    pb.update(delta)
                if ok or failed:
                    break
                time.sleep(wait_interval)

    if ok:
        click.secho("Package synchronised successfully!", fg="green")
        return

    click.secho(
        "Package failed to synchronise during stage: %(stage)s"
        % {"stage": click.style(stage_str or "Unknown", fg="yellow")},
        fg="red",
    )

    if reason:
        click.secho(
            "Reason given: %(reason)s" % {"reason": click.style(reason, fg="yellow")},
            fg="red",
        )

        # pylint: disable=fixme
        # FIXME: The API should communicate "no retry" fails
        if "package should be deleted" in reason and attempts > 1:
            click.secho(
                "This is not recoverable, so stopping further attempts!", fg="red"
            )
            click.echo()
            attempts = 0

    if attempts + 1 > 0:
        # Show attempts upto and including zero attempts left
        click.secho(
            "Attempts left: %(left)s (%(action)s)"
            % {
                "left": click.style(six.text_type(attempts), bold=True),
                "action": "trying again" if attempts > 0 else "giving up",
            }
        )
        click.echo()

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
    **kwargs
):
    """Upload package files and create a new package."""
    # pylint: disable=unused-argument
    owner, repo = owner_repo

    # 1. Validate package create parameters
    validate_create_package(
        ctx=ctx,
        opts=opts,
        owner=owner,
        repo=repo,
        package_type=package_type,
        skip_errors=skip_errors,
        **kwargs
    )

    # 2. Validate file upload parameters
    md5_checksums = {}
    for k, v in kwargs.items():
        if not v or not k.endswith("_file"):
            continue

        md5_checksums[k] = validate_upload_file(
            ctx=ctx,
            opts=opts,
            owner=owner,
            repo=repo,
            filepath=v,
            skip_errors=skip_errors,
        )

    if dry_run:
        click.echo()
        click.secho("You requested a dry run so skipping upload.", fg="yellow")
        return

    # 3. Upload any arguments that look like files
    for k, v in kwargs.items():
        if not v or not k.endswith("_file"):
            continue

        kwargs[k] = upload_file(
            ctx=ctx,
            opts=opts,
            owner=owner,
            repo=repo,
            filepath=v,
            skip_errors=skip_errors,
            md5_checksum=md5_checksums[k],
        )

    # 4. Create the package with package files and additional arguments
    _, slug = create_package(
        ctx=ctx,
        opts=opts,
        owner=owner,
        repo=repo,
        package_type=package_type,
        skip_errors=skip_errors,
        **kwargs
    )

    if no_wait_for_sync:
        return

    # 5. (optionally) Wait for the package to synchronise
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


def create_push_handlers():
    """Create a handler for upload per package format."""
    # pylint: disable=fixme
    # HACK: hacky territory - Dynamically generate a handler for each of the
    # package formats, until we have slightly more clever 'guess type'
    # handling. :-)
    handlers = create_push_handlers.handlers = {}
    context = create_push_handlers.context = get_package_formats()

    for key, parameters in six.iteritems(context):
        kwargs = parameters.copy()

        # Remove standard arguments
        kwargs.pop("package_file")
        if "distribution" in parameters:
            has_distribution_param = True
            kwargs.pop("distribution")
        else:
            has_distribution_param = False

        has_additional_params = len(kwargs) > 0

        help_text = """
            Push/upload a new %(type)s package upstream.
            """ % {
            "type": key.capitalize()
        }

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
        @decorators.common_api_auth_options
        @decorators.common_cli_config_options
        @decorators.common_cli_output_options
        @decorators.common_package_action_options
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
            "-n",
            "--dry-run",
            default=False,
            is_flag=True,
            help="Execute in dry run mode (don't upload anything.)",
        )
        @click.pass_context
        def push_handler(ctx, *args, **kwargs):
            """Handle upload for a specific package format."""
            parameters = context.get(ctx.info_name)
            kwargs["package_type"] = ctx.info_name

            owner_repo = kwargs.pop("owner_repo")
            if "distribution" in parameters:
                kwargs["distribution"] = "/".join(owner_repo[2:])
                owner_repo = owner_repo[0:2]
            kwargs["owner_repo"] = owner_repo

            package_files = kwargs.pop("package_file")
            if not isinstance(package_files, tuple):
                package_files = (package_files,)

            for package_file in package_files:
                kwargs["package_file"] = package_file

                try:
                    click.echo()
                    upload_files_and_create_package(ctx, *args, **kwargs)
                except ApiException:
                    click.secho("Skipping error and moving on.", fg="yellow")

                click.echo()

        # Add any additional arguments
        for k, info in six.iteritems(kwargs):
            option_kwargs = {}
            option_name_fmt = "--%(key)s"

            if k.endswith("_file"):
                # Treat parameters that end with _file as uploadable filepaths.
                option_kwargs["type"] = ExpandPath(
                    dir_okay=False, exists=True, writable=False, resolve_path=True
                )
            elif info["type"] == "bool":
                option_name_fmt = "--%(key)s/--no-%(key)s"
                option_kwargs["is_flag"] = True
            else:
                option_kwargs["type"] = str

            option_name = option_name_fmt % {"key": k.replace("_", "-")}
            decorator = click.option(
                option_name,
                required=info["required"],
                help=info["help"],
                **option_kwargs
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
