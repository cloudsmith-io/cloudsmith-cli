"""CLI/Commands - Download packages."""

import os

import click

from ...core.download import (
    get_download_url,
    get_package_detail,
    get_package_files,
    resolve_all_packages,
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
    "--tag",
    "tag_filter",
    help="Filter by package tag (e.g., 'latest', 'stable'). Use --format, --arch, --os for metadata filters.",
)
@click.option(
    "--filename",
    "filename_filter",
    help="Filter by package filename (e.g., 'mypackage.nupkg'). Supports glob patterns (e.g., '*.snupkg').",
)
@click.option(
    "--download-all",
    is_flag=True,
    help="Download all matching packages instead of erroring on multiple matches.",
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
    tag_filter,
    filename_filter,
    download_all,
    outfile,
    overwrite,
    all_files,
    dry_run,
    yes,
):
    """
    Download a package from a Cloudsmith repository.

    This command downloads a package binary from a Cloudsmith repository. You can
    filter packages by version, format, operating system, architecture, tags, and
    filename.

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
    # Download a package with a specific tag
    cloudsmith download myorg/myrepo mypackage --tag latest

    \b
    # Download by filename (exact or glob pattern)
    cloudsmith download myorg/myrepo TestSymbolPkg --filename '*.nupkg'
    cloudsmith download myorg/myrepo TestSymbolPkg --filename 'TestSymbolPkg.1.0.24406.nupkg'

    \b
    # Download all matching packages (e.g., .nupkg and .snupkg with same name/version)
    cloudsmith download myorg/myrepo TestSymbolPkg --version 1.0.24406 --download-all

    \b
    # Download all associated files (POM, sources, javadoc, etc.) for a Maven/NuGet package
    cloudsmith download myorg/myrepo mypackage --all-files

    \b
    # Download all files to a custom directory
    cloudsmith download myorg/myrepo mypackage --all-files --outfile ./my-package-dir

    For private repositories, set: export CLOUDSMITH_API_KEY=your_api_key

    If multiple packages match your criteria, you'll see a selection table unless
    you use --yes to automatically select the best match (highest version, then newest),
    or --download-all to download all matches.

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

    # Common filter kwargs shared by resolve_package and resolve_all_packages
    filter_kwargs = dict(
        owner=owner,
        repo=repo,
        name=name,
        version=version,
        format_filter=format_filter,
        os_filter=os_filter,
        arch_filter=arch_filter,
        tag_filter=tag_filter,
        filename_filter=filename_filter,
    )

    # --download-all: resolve all matching packages and download each one
    if download_all:
        context_msg = "Failed to find packages!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                packages = resolve_all_packages(**filter_kwargs)

        if not use_stderr:
            click.secho("OK", fg="green")

        _download_all_packages(
            ctx=ctx,
            opts=opts,
            packages=packages,
            owner=owner,
            repo=repo,
            session=session,
            auth_headers=auth_headers,
            outfile=outfile,
            overwrite=overwrite,
            all_files=all_files,
            dry_run=dry_run,
            use_stderr=use_stderr,
        )
        return

    # Single-package mode (default)
    context_msg = "Failed to find package!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            package = resolve_package(**filter_kwargs, yes=yes)

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


def _download_all_packages(  # noqa: C901
    *,
    ctx,
    opts,
    packages,
    owner,
    repo,
    session,
    auth_headers,
    outfile,
    overwrite,
    all_files,
    dry_run,
    use_stderr,
):
    """Download all matching packages into a directory."""
    # Determine output directory
    if outfile:
        output_dir = os.path.abspath(outfile)
    else:
        # Use current directory
        output_dir = os.path.abspath(".")

    if dry_run:
        click.echo()
        click.echo(f"Dry run - would download {len(packages)} package(s):")
        click.echo(f"  To directory: {output_dir}")
        click.echo()
        for i, pkg in enumerate(packages, 1):
            filename = pkg.get("filename", "unknown")
            size = _format_package_size(pkg)
            click.echo(
                f"  {i}. {pkg.get('name')} v{pkg.get('version')} "
                f"({pkg.get('format')}) - {filename} [{size}]"
            )
            if all_files:
                # Show sub-files if --all-files
                context_msg = "Failed to get package details!"
                with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                    detail = get_package_detail(
                        owner=owner, repo=repo, identifier=pkg["slug"]
                    )
                sub_files = get_package_files(detail)
                for f in sub_files:
                    primary = " (primary)" if f.get("is_primary") else ""
                    click.echo(
                        f"     [{f.get('tag', 'file')}] {f['filename']}{primary}"
                    )
        return

    # Create output directory if needed
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    elif not os.path.isdir(output_dir):
        raise click.ClickException(
            f"Output path '{output_dir}' exists but is not a directory."
        )

    if not use_stderr:
        click.echo(f"\nDownloading {len(packages)} package(s) to: {output_dir}")
        click.echo()

    all_downloaded_files = []
    total_success = 0
    total_failed = 0

    for pkg_idx, pkg in enumerate(packages, 1):
        pkg_name = pkg.get("name", "unknown")
        pkg_version = pkg.get("version", "unknown")
        pkg_filename = pkg.get("filename", "")

        if not use_stderr:
            click.echo(
                f"[{pkg_idx}/{len(packages)}] {pkg_name} v{pkg_version} "
                f"({pkg_filename})"
            )

        if all_files:
            # Download all sub-files for this package
            context_msg = f"Failed to get details for {pkg_name}!"
            with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                detail = get_package_detail(
                    owner=owner, repo=repo, identifier=pkg["slug"]
                )
            sub_files = get_package_files(detail)

            for file_info in sub_files:
                filename = file_info["filename"]
                file_url = file_info["cdn_url"]
                file_path = os.path.join(output_dir, filename)
                tag = file_info.get("tag", "file")

                if not use_stderr:
                    click.echo(f"  [{tag}] {filename} ...", nl=False)

                try:
                    context_msg = f"Failed to download {filename}!"
                    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                        stream_download(
                            url=file_url,
                            outfile=file_path,
                            session=session,
                            headers=auth_headers,
                            overwrite=overwrite,
                            quiet=True,
                        )
                    if not use_stderr:
                        click.secho(" OK", fg="green")
                    total_success += 1
                    all_downloaded_files.append(
                        {
                            "filename": filename,
                            "path": file_path,
                            "package": pkg_name,
                            "version": pkg_version,
                            "tag": tag,
                            "status": "OK",
                        }
                    )
                except Exception as e:  # pylint: disable=broad-except
                    if not use_stderr:
                        click.secho(" FAILED", fg="red")
                    total_failed += 1
                    all_downloaded_files.append(
                        {
                            "filename": filename,
                            "path": file_path,
                            "package": pkg_name,
                            "version": pkg_version,
                            "tag": tag,
                            "status": "FAILED",
                            "error": str(e),
                        }
                    )
        else:
            # Download the primary package file
            download_url = pkg.get("cdn_url") or pkg.get("download_url")
            filename = pkg_filename or f"{pkg_name}-{pkg_version}"
            file_path = os.path.join(output_dir, filename)

            if not download_url:
                # Fall back to detailed package info
                context_msg = f"Failed to get details for {pkg_name}!"
                with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                    detail = get_package_detail(
                        owner=owner, repo=repo, identifier=pkg["slug"]
                    )
                    download_url = (
                        detail.get("cdn_url")
                        or detail.get("download_url")
                        or detail.get("file_url")
                    )

            if not download_url:
                if not use_stderr:
                    click.secho("  No download URL available - SKIPPED", fg="yellow")
                total_failed += 1
                all_downloaded_files.append(
                    {
                        "filename": filename,
                        "path": file_path,
                        "package": pkg_name,
                        "version": pkg_version,
                        "status": "FAILED",
                        "error": "No download URL",
                    }
                )
                continue

            if not use_stderr:
                click.echo(f"  Downloading {filename} ...", nl=False)

            try:
                context_msg = f"Failed to download {filename}!"
                with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                    stream_download(
                        url=download_url,
                        outfile=file_path,
                        session=session,
                        headers=auth_headers,
                        overwrite=overwrite,
                        quiet=True,
                    )
                if not use_stderr:
                    click.secho(" OK", fg="green")
                total_success += 1
                all_downloaded_files.append(
                    {
                        "filename": filename,
                        "path": file_path,
                        "package": pkg_name,
                        "version": pkg_version,
                        "status": "OK",
                    }
                )
            except Exception as e:  # pylint: disable=broad-except
                if not use_stderr:
                    click.secho(" FAILED", fg="red")
                total_failed += 1
                all_downloaded_files.append(
                    {
                        "filename": filename,
                        "path": file_path,
                        "package": pkg_name,
                        "version": pkg_version,
                        "status": "FAILED",
                        "error": str(e),
                    }
                )

    # Build JSON output
    json_output = {
        "packages": [
            {
                "name": p.get("name"),
                "version": p.get("version"),
                "format": p.get("format"),
                "filename": p.get("filename"),
                "slug": p.get("slug"),
            }
            for p in packages
        ],
        "output_directory": output_dir,
        "files": all_downloaded_files,
        "summary": {
            "total_packages": len(packages),
            "total_files": total_success + total_failed,
            "success": total_success,
            "failed": total_failed,
        },
    }

    if utils.maybe_print_as_json(opts, json_output):
        return

    click.echo()
    total = total_success + total_failed
    if total_failed == 0:
        click.secho(
            f"All {total_success} file(s) from {len(packages)} package(s) "
            f"downloaded successfully!",
            fg="green",
        )
    else:
        click.secho(
            f"Downloaded {total_success}/{total} file(s) from "
            f"{len(packages)} package(s).",
            fg="yellow",
        )


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
