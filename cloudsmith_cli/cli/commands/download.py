"""CLI/Commands - Download packages."""

# Copyright 2025 Cloudsmith Ltd

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
def download(
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
    use_stderr = utils.should_use_stderr(opts)

    if not use_stderr:
        click.echo(
            f"Looking for package '{click.style(name, bold=True)}' in "
            f"{click.style(owner, bold=True)}/{click.style(repo, bold=True)} ...",
        )

    # Step 1: Authenticate
    session, auth_headers, auth_source = resolve_auth(opts)
    if opts.debug:
        click.echo(f"Using authentication: {auth_source}", err=True)

    # Step 2: Find package(s)
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
    packages = _find_packages(ctx, opts, filter_kwargs, download_all, yes, use_stderr)

    # Step 3: Resolve download items (url + output path for each file)
    download_items = _resolve_download_items(
        ctx, opts, packages, owner, repo, all_files, outfile, use_stderr
    )

    # Step 4: Dry-run or download
    if dry_run:
        _display_dry_run(packages, download_items, all_files)
        return

    _perform_downloads(
        ctx,
        opts,
        packages,
        download_items,
        session,
        auth_headers,
        overwrite,
        all_files,
        use_stderr,
    )


# ---------------------------------------------------------------------------
# Step 2: Find packages
# ---------------------------------------------------------------------------


def _find_packages(
    ctx: click.Context,
    opts,
    filter_kwargs: dict,
    download_all: bool,
    yes: bool,
    use_stderr: bool,
) -> list:
    """Find matching packages using the API."""
    if download_all:
        context_msg = "Failed to find packages!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                packages = resolve_all_packages(**filter_kwargs)
    else:
        context_msg = "Failed to find package!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                packages = [resolve_package(**filter_kwargs, yes=yes)]

    if not use_stderr:
        click.secho("OK", fg="green")

    return packages


# ---------------------------------------------------------------------------
# Step 3: Resolve download items
# ---------------------------------------------------------------------------


def _resolve_download_items(
    ctx: click.Context,
    opts,
    packages: list,
    owner: str,
    repo: str,
    all_files: bool,
    outfile: str,
    use_stderr: bool,
) -> list:
    """
    Resolve each package into a list of download items.

    Returns a list of dicts, each with keys:
        filename, url, output_path, tag, is_primary, size, package_name,
        package_version, status
    """
    items = []

    for pkg in packages:
        if all_files:
            items.extend(
                _resolve_all_files_items(
                    ctx, opts, pkg, owner, repo, outfile, use_stderr
                )
            )
        else:
            items.append(
                _resolve_single_file_item(
                    ctx,
                    opts,
                    pkg,
                    owner,
                    repo,
                    outfile,
                    len(packages) > 1,
                    use_stderr,
                )
            )

    return items


def _resolve_all_files_items(
    ctx: click.Context,
    opts,
    pkg: dict,
    owner: str,
    repo: str,
    outfile: str,
    use_stderr: bool,
) -> list:
    """Resolve all sub-files for a single package (--all-files mode)."""
    pkg_name = pkg.get("name", "unknown")
    pkg_version = pkg.get("version", "unknown")

    if not use_stderr:
        click.echo("Getting package details ...", nl=False)

    context_msg = f"Failed to get details for {pkg_name}!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with maybe_spinner(opts):
            detail = get_package_detail(owner=owner, repo=repo, identifier=pkg["slug"])

    if not use_stderr:
        click.secho("OK", fg="green")

    sub_files = get_package_files(detail)
    if not sub_files:
        raise click.ClickException("No downloadable files found for this package.")

    # Determine output directory
    if outfile:
        output_dir = os.path.abspath(outfile)
    else:
        output_dir = os.path.abspath(f"{pkg_name}-{pkg_version}")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    elif not os.path.isdir(output_dir):
        raise click.ClickException(
            f"Output path '{output_dir}' exists but is not a directory."
        )

    items = []
    for f in sub_files:
        items.append(
            {
                "filename": f["filename"],
                "url": f["cdn_url"],
                "output_path": _safe_join(output_dir, f["filename"]),
                "tag": f.get("tag", "file"),
                "is_primary": f.get("is_primary", False),
                "size": f.get("size", 0),
                "package_name": pkg_name,
                "package_version": pkg_version,
                "status": None,
            }
        )
    return items


def _resolve_single_file_item(
    ctx: click.Context,
    opts,
    pkg: dict,
    owner: str,
    repo: str,
    outfile: str,
    multi_package: bool,
    use_stderr: bool,
) -> dict:
    """Resolve a single primary file for a package."""
    pkg_name = pkg.get("name", "unknown")
    pkg_version = pkg.get("version", "unknown")

    download_url = get_download_url(pkg)

    if not download_url:
        # Fall back to detailed package info
        if not use_stderr:
            click.echo("Getting package details ...", nl=False)
        context_msg = "Failed to get package details!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                detail = get_package_detail(
                    owner=owner, repo=repo, identifier=pkg["slug"]
                )
                download_url = get_download_url(detail or pkg)
        if not use_stderr:
            click.secho("OK", fg="green")

    # Determine output path
    if outfile and not multi_package:
        output_path = os.path.abspath(outfile)
    elif multi_package:
        output_dir = os.path.abspath(outfile) if outfile else os.path.abspath(".")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        filename = pkg.get("filename") or f"{pkg_name}-{pkg_version}"
        output_path = _safe_join(output_dir, filename)
    elif pkg.get("filename"):
        output_path = os.path.abspath(os.path.basename(pkg["filename"]))
    else:
        pkg_format = pkg.get("format", "bin")
        extension = _get_extension_for_format(pkg_format)
        output_path = os.path.abspath(f"{pkg_name}-{pkg_version}.{extension}")

    return {
        "filename": os.path.basename(output_path),
        "url": download_url,
        "output_path": output_path,
        "tag": "file",
        "is_primary": True,
        "size": pkg.get("size", 0),
        "package_name": pkg_name,
        "package_version": pkg_version,
        "status": None,
    }


# ---------------------------------------------------------------------------
# Step 4a: Dry-run display (shared by all paths)
# ---------------------------------------------------------------------------


def _display_dry_run(packages: list, download_items: list, all_files: bool) -> None:
    """Display what would be downloaded without actually downloading."""
    click.echo()
    click.echo(
        f"Dry run - would download {len(download_items)} file(s) "
        f"from {len(packages)} package(s):"
    )
    click.echo()

    for item in download_items:
        primary_marker = " (primary)" if item.get("is_primary") else ""
        size = _format_file_size(item.get("size", 0))
        tag = item.get("tag", "file")
        click.echo(f"  [{tag}] {item['filename']}{primary_marker} - {size}")
        click.echo(f"    Package: {item['package_name']} v{item['package_version']}")
        click.echo(f"    To: {item['output_path']}")


# ---------------------------------------------------------------------------
# Step 4b: Perform downloads
# ---------------------------------------------------------------------------


def _perform_downloads(
    ctx: click.Context,
    opts,
    packages: list,
    download_items: list,
    session,
    auth_headers: dict,
    overwrite: bool,
    all_files: bool,
    use_stderr: bool,
) -> None:
    """Download all resolved items and report results."""
    total = len(download_items)
    if not use_stderr:
        click.echo(f"\nDownloading {total} file(s):")
        click.echo()

    results = []

    for idx, item in enumerate(download_items, 1):
        filename = item["filename"]
        url = item["url"]
        output_path = item["output_path"]
        tag = item.get("tag", "file")
        primary_marker = " (primary)" if item.get("is_primary") else ""

        # Handle missing download URL as a skip, not a failure
        if not url:
            _echo_progress(
                use_stderr, f"[{idx}/{total}] [{tag}] {filename}{primary_marker} ..."
            )
            _echo_status(use_stderr, " SKIPPED", fg="yellow")
            results.append({**item, "status": "SKIPPED", "error": "No download URL"})
            continue

        _echo_progress(
            use_stderr, f"[{idx}/{total}] [{tag}] {filename}{primary_marker} ..."
        )

        try:
            context_msg = f"Failed to download {filename}!"
            with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
                stream_download(
                    url=url,
                    outfile=output_path,
                    session=session,
                    headers=auth_headers,
                    overwrite=overwrite,
                    quiet=True,
                )
            _echo_status(use_stderr, " OK", fg="green")
            results.append({**item, "status": "OK"})
        except Exception as e:  # pylint: disable=broad-except
            _echo_status(use_stderr, " FAILED", fg="red")
            results.append({**item, "status": "FAILED", "error": str(e)})

    # Report results
    _report_results(opts, packages, results, all_files)


def _echo_progress(use_stderr: bool, message: str) -> None:
    """Print progress message to stdout or stderr."""
    click.echo(message, nl=False, err=use_stderr)


def _echo_status(use_stderr: bool, message: str, fg: str = None) -> None:
    """Print styled status message to stdout or stderr."""
    if fg and not use_stderr:
        click.secho(message, fg=fg)
    elif use_stderr:
        click.echo(message, err=True)
    else:
        click.echo(message)


def _report_results(opts, packages: list, results: list, all_files: bool) -> None:
    """Build JSON output and print summary."""
    success = [r for r in results if r["status"] == "OK"]
    failed = [r for r in results if r["status"] == "FAILED"]
    skipped = [r for r in results if r["status"] == "SKIPPED"]

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
        "files": [
            {
                "filename": r["filename"],
                "path": r["output_path"],
                "package": r["package_name"],
                "version": r["package_version"],
                "tag": r.get("tag", "file"),
                "is_primary": r.get("is_primary", False),
                "size": r.get("size", 0),
                "status": r["status"],
                **({"error": r["error"]} if "error" in r else {}),
            }
            for r in results
        ],
        "summary": {
            "total_packages": len(packages),
            "total_files": len(results),
            "success": len(success),
            "failed": len(failed),
            "skipped": len(skipped),
        },
    }

    if utils.maybe_print_as_json(opts, json_output):
        return

    click.echo()
    if not failed and not skipped:
        click.secho(f"All {len(success)} file(s) downloaded successfully!", fg="green")
    else:
        click.secho(f"Downloaded {len(success)}/{len(results)} file(s).", fg="yellow")
        if failed:
            click.echo("\nFailed files:")
            for r in failed:
                click.echo(f"  - {r['filename']}: {r.get('error', 'Unknown error')}")
        if skipped:
            click.echo("\nSkipped files (no download URL):")
            for r in skipped:
                click.echo(f"  - {r['filename']}")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _safe_join(base_dir: str, filename: str) -> str:
    """Safely join base_dir and filename, preventing path traversal."""
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise click.ClickException(f"Invalid filename '{filename}'.")
    result = os.path.join(base_dir, safe_name)
    if not os.path.realpath(result).startswith(os.path.realpath(base_dir) + os.sep):
        raise click.ClickException(
            f"Filename '{filename}' resolves outside the target directory."
        )
    return result


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
