"""CLI/Commands - Download packages."""

import os

import click

from ...core.download import (
    get_download_url,
    get_package_detail,
    get_package_files,
    resolve_auth,
    resolve_package,
    stream_download,
)
from .. import decorators, utils, validators
from ..exceptions import handle_api_exceptions
from ..utils import maybe_spinner
from .main import main


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo", metavar="OWNER/REPO", callback=validators.validate_owner_repo
)
@click.argument("name", required=True)
@click.option(
    "--version",
    help="Package version to download (e.g., '1.0.0'). If not specified, searches all versions.",
)
@click.option(
    "--format",
    "format_filter",
    help="Package format filter (e.g., 'deb', 'rpm', 'python', 'npm').",
)
@click.option(
    "--os", "os_filter", help="Operating system filter (e.g., 'ubuntu', 'centos')."
)
@click.option(
    "--arch", "arch_filter", help="Architecture filter (e.g., 'amd64', 'arm64')."
)
@click.option(
    "--outfile",
    type=click.Path(),
    help="Output file path. If not specified, uses the package filename.",
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    help="Overwrite existing files (default: fail if file exists).",
)
@click.option(
    "--all-files",
    is_flag=True,
    help="Download all associated files (POM, sources, javadoc, etc.) into a folder.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be downloaded without actually downloading.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Automatically select the best match when multiple packages are found.",
)
@click.pass_context
def download(  # noqa: C901
    ctx,
    opts,
    owner_repo,
    name,
    version,
    format_filter,
    os_filter,
    arch_filter,
    outfile,
    overwrite,
    all_files,
    dry_run,
    yes,
):
    """
    Download a package from a Cloudsmith repository.

    This command downloads a package binary from a Cloudsmith repository. You can
    filter packages by version, format, operating system, and architecture.

    Examples:

    \b
    # Download the latest version of 'mypackage'
    cloudsmith download myorg/myrepo mypackage

    \b
    # Download a specific version
    cloudsmith download myorg/myrepo mypackage --version 1.2.3

    \b
    # Download with filters and custom output name
    cloudsmith download myorg/myrepo mypackage --format deb --arch amd64 --outfile my-package.deb

    \b
    # Download all associated files (POM, sources, javadoc, etc.) for a Maven/NuGet package
    cloudsmith download myorg/myrepo mypackage --all-files

    \b
    # Download all files to a custom directory
    cloudsmith download myorg/myrepo mypackage --all-files --outfile ./my-package-dir

    For private repositories, set: export CLOUDSMITH_API_KEY=your_api_key

    If multiple packages match your criteria, you'll see a selection table unless
    you use --yes to automatically select the best match (highest version, then newest).

    When using --all-files, all associated files (such as POM files, sources, javadoc,
    SBOM, etc.) will be downloaded into a folder named {package-name}-{version} unless
    you specify a custom directory with --outfile.
    """
    owner, repo = owner_repo

    # Use stderr for messages if output is JSON
    use_stderr = utils.should_use_stderr(opts)

    if not use_stderr:
        click.echo(
            f"Looking for package '{click.style(name, bold=True)}' in "
            f"{click.style(owner, bold=True)}/{click.style(repo, bold=True)} ...",
        )

    # Resolve authentication
    session, auth_headers, auth_source = resolve_auth(opts)

    if opts.debug:
        click.echo(f"Using authentication: {auth_source}", err=True)

    # Find the package
    context_msg = "Failed to find package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package = resolve_package(
                owner=owner,
                repo=repo,
                name=name,
                version=version,
                format_filter=format_filter,
                os_filter=os_filter,
                arch_filter=arch_filter,
                yes=yes,
            )

    if not use_stderr:
        click.secho("OK", fg="green")

    # Get detailed package info if we need more fields for download URL or all files
    package_detail = None

    if all_files:
        # For --all-files, we always need the detailed package info to get the files array
        if not use_stderr:
            click.echo("Getting package details ...", nl=False)
        context_msg = "Failed to get package details!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                package_detail = get_package_detail(
                    owner=owner, repo=repo, identifier=package["slug"]
                )
        if not use_stderr:
            click.secho("OK", fg="green")

        # Get all downloadable files
        files_to_download = get_package_files(package_detail)

        if not files_to_download:
            raise click.ClickException("No downloadable files found for this package.")

        # Create output directory for all files
        if outfile:
            # If user specified an outfile, use it as the directory
            output_dir = os.path.abspath(outfile)
        else:
            # Create directory named: {package-name}-{version}
            pkg_name = package_detail.get("name", name)
            pkg_version = package_detail.get("version", "unknown")
            output_dir = os.path.abspath(f"{pkg_name}-{pkg_version}")

        # Create directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        elif not os.path.isdir(output_dir):
            raise click.ClickException(
                f"Output path '{output_dir}' exists but is not a directory."
            )

        if dry_run:
            click.echo()
            click.echo("Dry run - would download:")
            click.echo(f"  Package: {package.get('name')} v{package.get('version')}")
            click.echo(f"  Format: {package.get('format')}")
            click.echo(f"  Files: {len(files_to_download)}")
            click.echo(f"  To directory: {output_dir}")
            click.echo()
            for file_info in files_to_download:
                primary_marker = " (primary)" if file_info.get("is_primary") else ""
                click.echo(
                    f"    [{file_info.get('tag', 'file')}] {file_info['filename']}{primary_marker} - "
                    f"{_format_file_size(file_info.get('size', 0))}"
                )
            return

        # Download all files
        if not use_stderr:
            click.echo(f"\nDownloading {len(files_to_download)} files to: {output_dir}")
            click.echo()

        success_count = 0
        failed_files = []
        downloaded_files = []

        for idx, file_info in enumerate(files_to_download, 1):
            filename = file_info["filename"]
            file_url = file_info["cdn_url"]
            output_path = os.path.join(output_dir, filename)

            primary_marker = " (primary)" if file_info.get("is_primary") else ""
            tag = file_info.get("tag", "file")

            if not use_stderr:
                click.echo(
                    f"[{idx}/{len(files_to_download)}] [{tag}] {filename}{primary_marker} ...",
                    nl=False,
                )
            else:
                click.echo(
                    f"[{idx}/{len(files_to_download)}] [{tag}] {filename}{primary_marker} ...",
                    nl=False,
                    err=True,
                )

            try:
                context_msg = f"Failed to download {filename}!"
                with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                    stream_download(
                        url=file_url,
                        outfile=output_path,
                        session=session,
                        headers=auth_headers,
                        overwrite=overwrite,
                        quiet=True,  # Suppress per-file progress bars for cleaner output
                    )
                if not use_stderr:
                    click.secho(" OK", fg="green")
                else:
                    click.echo(" OK", err=True)
                success_count += 1
                downloaded_files.append(
                    {
                        "filename": filename,
                        "path": output_path,
                        "tag": tag,
                        "is_primary": file_info.get("is_primary", False),
                        "size": file_info.get("size", 0),
                        "status": "OK",
                    }
                )
            except Exception as e:  # pylint: disable=broad-except
                if not use_stderr:
                    click.secho(" FAILED", fg="red")
                else:
                    click.echo(" FAILED", err=True)
                failed_files.append((filename, str(e)))
                downloaded_files.append(
                    {
                        "filename": filename,
                        "path": output_path,
                        "tag": tag,
                        "is_primary": file_info.get("is_primary", False),
                        "size": file_info.get("size", 0),
                        "status": "FAILED",
                        "error": str(e),
                    }
                )

        # Build JSON output for all-files download
        json_output = {
            "package": {
                "name": package.get("name"),
                "version": package.get("version"),
                "format": package.get("format"),
                "slug": package.get("slug"),
            },
            "output_directory": output_dir,
            "files": downloaded_files,
            "summary": {
                "total": len(files_to_download),
                "success": success_count,
                "failed": len(failed_files),
            },
        }

        if utils.maybe_print_as_json(opts, json_output):
            return

        click.echo()
        if success_count == len(files_to_download):
            click.secho(
                f"All {success_count} files downloaded successfully!",
                fg="green",
            )
        else:
            click.secho(
                f"Downloaded {success_count}/{len(files_to_download)} files.",
                fg="yellow",
            )
            if failed_files:
                click.echo("\nFailed files:")
                for filename, error in failed_files:
                    click.echo(f"  - {filename}: {error}")

        return

    # Single file download (original behavior)
    download_url = get_download_url(package)

    if not download_url:
        # Try getting detailed package info
        if not use_stderr:
            click.echo("Getting package details ...", nl=False)
        context_msg = "Failed to get package details!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                package_detail = get_package_detail(
                    owner=owner, repo=repo, identifier=package["slug"]
                )
                download_url = get_download_url(package_detail or package)
        if not use_stderr:
            click.secho("OK", fg="green")

    # Determine output filename
    if not outfile:
        # Extract filename from URL or use package name + format
        if package.get("filename"):
            outfile = package["filename"]
        else:
            # Fallback to package name with extension based on format
            pkg_format = package.get("format", "bin")
            extension = _get_extension_for_format(pkg_format)
            outfile = f"{package.get('name', name)}-{package.get('version', 'latest')}.{extension}"

    # Ensure outfile is not a directory
    outfile = os.path.abspath(outfile)

    if dry_run:
        click.echo()
        click.echo("Dry run - would download:")
        click.echo(f"  Package: {package.get('name')} v{package.get('version')}")
        click.echo(f"  Format: {package.get('format')}")
        click.echo(f"  Size: {_format_package_size(package)}")
        click.echo(f"  From: {download_url}")
        click.echo(f"  To: {outfile}")
        click.echo(f"  Overwrite: {'Yes' if overwrite else 'No'}")
        return

    # Perform the download
    context_msg = "Failed to download package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        stream_download(
            url=download_url,
            outfile=outfile,
            session=session,
            headers=auth_headers,
            overwrite=overwrite,
            quiet=utils.should_use_stderr(opts),
        )

    # Build JSON output for single-file download
    json_output = {
        "package": {
            "name": package.get("name"),
            "version": package.get("version"),
            "format": package.get("format"),
            "slug": package.get("slug"),
        },
        "output_directory": os.path.dirname(outfile),
        "files": [
            {
                "filename": os.path.basename(outfile),
                "path": outfile,
                "tag": "file",
                "is_primary": True,
                "size": package.get("size", 0),
                "status": "OK",
            }
        ],
        "summary": {
            "total": 1,
            "success": 1,
            "failed": 0,
        },
    }

    if utils.maybe_print_as_json(opts, json_output):
        return

    click.echo()
    click.secho("Download completed successfully!", fg="green")


def _get_extension_for_format(pkg_format: str) -> str:
    """Get appropriate file extension for package format."""
    format_extensions = {
        "deb": "deb",
        "rpm": "rpm",
        "python": "whl",
        "npm": "tgz",
        "maven": "jar",
        "nuget": "nupkg",
        "gem": "gem",
        "go": "tar.gz",
        "docker": "tar",
        "helm": "tgz",
        "raw": "bin",
        "terraform": "zip",
    }
    return format_extensions.get(pkg_format.lower(), "bin")


def _format_package_size(package: dict) -> str:
    """Format package size for display."""
    size = package.get("size", 0)
    return _format_file_size(size)


def _format_file_size(size: int) -> str:
    """Format file size in bytes to human-readable format."""
    if size == 0:
        return "Unknown"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} PB"
