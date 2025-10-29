"""CLI/Commands - Download packages."""

import os

import click

from ...core.download import (
    get_download_url,
    get_package_detail,
    resolve_auth,
    resolve_package,
    stream_download,
)
from .. import decorators, validators
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
    "--token",
    help="Entitlement token for private packages. Only used if no API key is configured.",
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
def download(  # pylint: disable=too-many-positional-arguments
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
    token,
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
    # Download a private package using an entitlement token
    cloudsmith download myorg/private-repo mypackage --token abcd1234efgh5678

    Authentication Priority:
    1. API key from CLOUDSMITH_API_KEY environment variable or --api-key option
    2. Entitlement token from --token option (only if no API key configured)

    For private repositories, set: export CLOUDSMITH_API_KEY=your_api_key

    If multiple packages match your criteria, you'll see a selection table unless
    you use --yes to automatically select the best match (highest version, then newest).
    """
    owner, repo = owner_repo

    # Use stderr for messages if output is JSON
    use_stderr = opts.output != "pretty"

    click.echo(
        f"Looking for package '{click.style(name, bold=True)}' in "
        f"{click.style(owner, bold=True)}/{click.style(repo, bold=True)} ...",
        err=use_stderr,
    )

    # Resolve authentication
    session, auth_headers, auth_source = resolve_auth(opts, token_opt=token)

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

    click.secho("OK", fg="green", err=use_stderr)

    # Get detailed package info if we need more fields for download URL
    package_detail = None
    download_url = get_download_url(package)

    if not download_url:
        # Try getting detailed package info
        click.echo("Getting package details ...", nl=False, err=use_stderr)
        context_msg = "Failed to get package details!"
        with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
            with maybe_spinner(opts):
                package_detail = get_package_detail(
                    owner=owner, repo=repo, identifier=package["slug"]
                )
                download_url = get_download_url(package_detail or package)
        click.secho("OK", fg="green", err=use_stderr)

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
            token=token if auth_source != "api-key" else None,
            overwrite=overwrite,
            quiet=opts.output != "pretty",
        )

    if opts.output == "pretty":
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
    if size == 0:
        return "Unknown"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} PB"
