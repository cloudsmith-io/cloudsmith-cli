"""CLI/Commands - Push packages."""
from __future__ import absolute_import, print_function, unicode_literals
import os
import time

import click
from click_didyoumean import DYMGroup
from click_spinner import spinner
import six
from ...core.api.files import (
    request_file_upload, upload_file as api_upload_file)
from ...core.api.packages import (
    create_package as api_create_package, get_package_status,
    get_package_formats)
from ...core import utils
from .. import decorators, validators
from ..exceptions import handle_api_exceptions
from ..types import ExpandPath
from . import main


def upload_file(ctx, opts, owner, repo, filepath):
    """Upload a package file via the API."""
    filename = click.format_filename(filepath)
    basename = os.path.basename(filename)

    click.echo(
        "Requesting file upload for '%(filename)s' ... " % {
            'filename': click.style(basename, bold=True)
        }, nl=False
    )

    context_msg = "Failed to request file upload!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            identifier, upload_url, upload_fields = request_file_upload(
                owner=owner,
                repo=repo,
                filepath=filename
            )

    click.secho("OK", fg='green')

    context_msg = "Failed to upload file!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        filesize = utils.get_file_size(filepath=filename)

        label = "Uploading '%(filename)s':" % {
            'filename': click.style(basename, bold=True)
        }

        fill_char = click.style('#', fg='green')
        empty_char = click.style('-', fg='red')

        with click.progressbar(
                length=filesize, label=label, fill_char=fill_char,
                empty_char=empty_char) as bar:
            def progress_callback(monitor):
                bar.update(monitor.bytes_read)

            api_upload_file(
                identifier=identifier,
                upload_url=upload_url,
                upload_fields=upload_fields,
                filepath=filename,
                callback=progress_callback
            )

    return identifier


def create_package(
        ctx, opts, owner, repo, package_file_id, package_type, **kwargs):
    """Create a new package via the API."""
    click.echo()
    click.echo(
        "Creating a new %(package_type)s package ... " % {
            'package_type': click.style(package_type, bold=True)
        }, nl=False
    )

    payload = {'package_file': package_file_id}
    if kwargs:
        payload.update(kwargs)

    context_msg = "Failed to create package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with spinner():
            slug_perm, slug = api_create_package(
                package_format=package_type,
                owner=owner,
                repo=repo,
                payload=payload
            )

    click.secho("OK", fg='green')

    click.echo(
        "Created: %(owner)s/%(repo)s/%(slug)s (%(slug_perm)s)" % {
            'owner': click.style(owner, fg='magenta'),
            'repo': click.style(repo, fg='blue'),
            'slug': click.style(slug, fg='green'),
            'slug_perm': click.style(slug_perm, bold=True)
        }
    )

    return slug_perm, slug


def wait_for_package_sync(ctx, opts, owner, repo, slug, wait_interval):
    """Wait for a package to synchronise (or fail)."""
    click.echo()
    completed = False
    label = "Synchronising '%(package)s':" % {
        'package': slug
    }

    fill_char = click.style('#', fg='green')
    empty_char = click.style('-', fg='red')
    status_str = 'Waiting'
    stage_str = None

    def display_status(current):
        if not stage_str:
            return status_str
        return "%(status)s / %(stage)s" % {
            'status': status_str,
            'stage': stage_str
        }

    context_msg = "Failed to synchronise file!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        last_progress = 0
        with click.progressbar(
                length=100, label=label, fill_char=fill_char,
                empty_char=empty_char, item_show_func=display_status) as bar:
            while True:
                res = get_package_status(owner, repo, slug)
                completed, failed, progress, status_str, stage_str = res
                delta = progress - last_progress
                if delta > 0:
                    last_progress = progress
                    bar.update(delta)
                if completed or failed:
                    break
                time.sleep(wait_interval)

    if completed:
        click.secho("Package synchronised successfully!", fg='green')
    else:
        click.secho("Package failed to synchronise!", fg='red')


def upload_files_and_create_package(
        ctx, opts, package_type, package_file, owner_repo, dry_run,
        no_wait_for_sync, wait_interval, **kwargs):
    """Upload package files and create a new package."""
    owner, repo = owner_repo

    # 1. Validate the arguments prior to uploading
    # FIXME: We haven't added the check endpoint in the API yet (soon)

    # 2. Upload the primary package file and store the id
    package_file_id = upload_file(
        ctx=ctx, opts=opts, owner=owner, repo=repo, filepath=package_file
    )

    # 3. Clean additional arguments, upload any that look like files
    for k, v in kwargs.items():
        if not v:
            del kwargs[k]
            continue

        if not k.endswith('_file'):
            continue

        kwargs[k] = upload_file(
            ctx=ctx, opts=opts, owner=owner, repo=repo, filepath=v
        )

    # 4. Create the package with package files and additional arguments
    slug_perm, slug = create_package(
        ctx=ctx, opts=opts, owner=owner, repo=repo,
        package_file_id=package_file_id, package_type=package_type,
        **kwargs
    )

    if no_wait_for_sync:
        return

    # 5. (optionally) Wait for the package to synchronise
    wait_for_package_sync(
        ctx=ctx, opts=opts, owner=owner, repo=repo, slug=slug,
        wait_interval=wait_interval
    )


@main.group(cls=DYMGroup)
@click.pass_context
def push(ctx):
    """
    Push/upload a new package to a repository.

    At the moment you need to specify the package format (see below) of
    the package you're uploading. Each package format may have additional
    options/parameters that are specific to that package format (e.g. the
    Maven backend has the concepts of artifact and group IDs).
    """


# Hacky territory - Dynamically generate a handler for each of the package
# formats, until we have slightly more clever "guess type" handling. :-)
PUSH_HANDLERS = {}  # For keeping references to the handlers
PUSH_CONTEXT = get_package_formats()

for key, parameters in six.iteritems(PUSH_CONTEXT):
    help_text=(
        """
        Push/upload a new %(type)s package upstream.

        - PACKAGE_FILE: The main file for the package.
        """ % {
            'type': key.capitalize()
        }
    )

    if 'distribution' in parameters:
        target_metavar = 'OWNER/REPO/DISTRO[/VERSION]'
        target_callback = validators.validate_owner_repo_distro
        help_text += """

        - OWNER/REPO/DISTRO[/VERSION]: Specify the OWNER namespace (i.e. user
        or org), the REPO name where the package file will be uploaded to,
        and the DISTRO and VERSION (for DISTRO) the package is for. All
        separated by a slash.

        Example: 'your-org/awesome-repo/ubuntu/xenial'.
        """
    else:
        target_metavar = 'OWNER/REPO'
        target_callback = validators.validate_owner_repo
        help_text += """

        - OWNER/REPO: Specify the OWNER namespace (i.e. user or org), and the
        REPO name where the package file will be uploaded to. All separated
        by a slash.

        Example: 'your-org/awesome-repo'.
        """

    @push.command(
        name=key,
        help=help_text
    )
    @click.argument(
        'owner_repo',
        metavar=target_metavar,
        callback=target_callback)
    @click.argument(
        'package_file', type=ExpandPath(
            dir_okay=False, exists=True, writable=False, resolve_path=True
        ))
    @click.option(
        '-n', '--dry-run', default=False, is_flag=True,
        help="Execute in dry run mode (don't upload anything.)")
    @click.option(
        '-W', '--no-wait-for-sync', default=False, is_flag=True,
        help="Wait for synchronisation to complete before exiting.")
    @click.option(
        '-I', '--wait-interval', default=5.0, type=float, show_default=True,
        help="The time in seconds to wait between checking operations.")
    @decorators.common_cli_config_options
    @decorators.common_cli_output_options
    @decorators.common_api_auth_options
    @decorators.initialise_api
    @click.pass_context
    def push_handler(ctx, *args, **kwargs):
        if kwargs['dry_run']:
            # FIXME: Too lazy to remove the option, not lazy enough to display
            # a warning. This is a note to self to actually implement it.
            click.secho(
                "Sorry, dry run mode isn't supported yet (coming soon!)",
                fg='yellow')
            ctx.exit(1)

        parameters = PUSH_CONTEXT.get(ctx.info_name)
        kwargs['package_type'] = ctx.info_name

        owner_repo = kwargs.pop('owner_repo')
        if 'distribution' in parameters:
            kwargs['distribution'] = '/'.join(owner_repo[2:])
            owner_repo = owner_repo[0:2]
        kwargs['owner_repo'] = owner_repo

        upload_files_and_create_package(ctx, *args, **kwargs)

    kwargs = parameters.copy()

    # Remove standard arguments
    kwargs.pop('package_file')
    if 'distribution' in parameters:
        kwargs.pop('distribution')

    # Add any additional arguments
    for k, info in six.iteritems(kwargs):
        # This is also a bit hacky. :-)
        if k.endswith('_file'):
            option_type=ExpandPath(
                dir_okay=False, exists=True, writable=False, resolve_path=True
            )
        else:
            option_type=str

        option_name = "--%(key)s" % {'key': k.replace('_', '-')}
        decorator = click.option(
            option_name, type=option_type, required=info['required'],
            help=info['help']
        )
        push_handler = decorator(push_handler)

    PUSH_HANDLERS[key] = push_handler
