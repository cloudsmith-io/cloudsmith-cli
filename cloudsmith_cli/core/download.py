"""Core download functionality for Cloudsmith packages."""

import hashlib
import os
from typing import Dict, List, Optional, Tuple

import click
import cloudsmith_api
import requests

from . import keyring, ratelimits, utils
from .api.exceptions import catch_raise_api_exception
from .api.packages import get_packages_api, list_packages
from .rest import create_requests_session


def resolve_auth(
    opts, api_key_opt: Optional[str] = None
) -> Tuple[requests.Session, Dict[str, str], str]:
    """
    Resolve authentication method and create session with appropriate headers.

    Args:
        opts: CLI options object containing existing auth config
        api_key_opt: Optional API key override from --api-key

    Returns:
        (session, headers, auth_source) where auth_source is 'api-key', 'sso', or 'none'
    """
    session = create_requests_session(
        error_retry_cb=getattr(opts, "error_retry_cb", None),
        respect_retry_after_header=getattr(opts, "rate_limit", True),
    )
    headers = {}
    auth_source = "none"

    # Follow the same authentication logic as the API initialization
    # Priority: explicit --api-key > SSO token > configured API key

    # First try to get SSO access token
    config = cloudsmith_api.Configuration()
    access_token = keyring.get_access_token(config.host)
    api_key = api_key_opt or getattr(opts, "api_key", None)

    if api_key:
        # Prioritize API key (from --api-key option or CLOUDSMITH_API_KEY env var) over SSO
        headers["X-Api-Key"] = api_key
        auth_source = "api-key"
    elif access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        auth_source = "sso"

    return session, headers, auth_source


def resolve_package(
    owner: str,
    repo: str,
    name: str,
    *,
    version: Optional[str] = None,
    format_filter: Optional[str] = None,
    os_filter: Optional[str] = None,
    arch_filter: Optional[str] = None,
    yes: bool = False,
) -> Dict:
    """
    Find a single package matching the criteria, handling multiple matches.

    Args:
        owner: Repository owner
        repo: Repository name
        name: Package name to search for
        version: Optional version filter
        format_filter: Optional format filter
        os_filter: Optional OS filter
        arch_filter: Optional architecture filter
        yes: If True, automatically select best match when multiple found

    Returns:
        The package dict

    Raises:
        click.ClickException: If 0 packages found (exit code 2) or >1 found without --yes (exit code 3)
    """
    # Build search query - use server-side filtering where possible
    query_parts = [f"name:{name}"]
    if version:
        query_parts.append(f"version:{version}")
    if format_filter:
        query_parts.append(f"format:{format_filter}")

    query = " AND ".join(query_parts)

    # Search for packages
    packages = []
    page = 1
    page_size = 100

    while True:
        page_packages, page_info = list_packages(
            owner=owner, repo=repo, query=query, page=page, page_size=page_size
        )

        if not page_packages:
            break

        packages.extend(page_packages)

        if not (page_info.is_valid and page_info.page < page_info.page_total):
            break

        page += 1

    # Apply client-side filters for fields not supported server-side
    # First, filter for exact name match (API does partial matching)
    filtered_packages = []
    for pkg in packages:
        # Exact name match (case-insensitive)
        if pkg.get("name", "").lower() != name.lower():
            continue
        # Apply OS filter
        if os_filter and pkg.get("distro_os") != os_filter:
            continue
        # Apply architecture filter
        if arch_filter and pkg.get("architecture") != arch_filter:
            continue
        filtered_packages.append(pkg)
    packages = filtered_packages

    # Handle results
    if not packages:
        exc = click.ClickException("No packages found matching the specified criteria.")
        exc.exit_code = 2
        raise exc

    if len(packages) == 1:
        return packages[0]

    # Multiple packages found
    if not yes:
        click.echo("Multiple packages found:")
        click.echo()

        # Display table of matches
        headers = ["#", "Name", "Version", "Format", "Size", "Created"]
        rows = []

        for i, pkg in enumerate(packages, 1):
            rows.append(
                [
                    str(i),
                    click.style(pkg.get("name", ""), fg="cyan"),
                    click.style(pkg.get("version", ""), fg="yellow"),
                    click.style(pkg.get("format", ""), fg="blue"),
                    click.style(_format_size(pkg.get("size", 0)), fg="green"),
                    click.style(_format_date(pkg.get("uploaded_at", "")), fg="white"),
                ]
            )

        # Import here to avoid circular imports
        from ..cli.utils import pretty_print_table

        pretty_print_table(headers, rows)
        click.echo()
        exc = click.ClickException(
            "Multiple packages found. Use --yes to auto-select the best match, or add more specific filters."
        )
        exc.exit_code = 3
        raise exc

    # Auto-select best match: highest version, then newest created_at
    best_package = _select_best_package(packages)

    click.echo(
        f"Auto-selected: {best_package.get('name')} v{best_package.get('version')} ({best_package.get('format')})"
    )

    return best_package


def get_download_url(package: Dict) -> str:
    """
    Get the download URL for a package.

    Args:
        package: Package dictionary from API

    Returns:
        Download URL string

    Raises:
        click.ClickException: If no download URL is available
    """
    # Check for common download URL fields
    download_url = (
        package.get("cdn_url")
        or package.get("download_url")
        or package.get("file_url")
        or package.get("url")
    )

    if not download_url:
        raise click.ClickException("Package does not have a download URL available.")

    return download_url


def get_package_files(package: Dict) -> List[Dict]:
    """
    Get all downloadable files associated with a package.

    Args:
        package: Package dictionary from API

    Returns:
        List of file dictionaries, each containing:
        - filename: The file name
        - cdn_url: Download URL
        - size: File size in bytes
        - tag: File type (pkg, pom, sources, javadoc, etc.)
        - is_primary: Whether this is the primary package file
        - checksum_md5, checksum_sha1, checksum_sha256, checksum_sha512: Checksums
    """
    files = package.get("files", [])

    if not files:
        # If no files array, return the main package as a single file
        return [
            {
                "filename": package.get("filename", "package"),
                "cdn_url": get_download_url(package),
                "size": package.get("size", 0),
                "tag": "pkg",
                "is_primary": True,
                "checksum_md5": package.get("checksum_md5"),
                "checksum_sha1": package.get("checksum_sha1"),
                "checksum_sha256": package.get("checksum_sha256"),
                "checksum_sha512": package.get("checksum_sha512"),
            }
        ]

    # Filter to only downloadable files with CDN URLs
    downloadable_files = []
    for file_info in files:
        if file_info.get("is_downloadable") and file_info.get("cdn_url"):
            downloadable_files.append(file_info)

    return downloadable_files


def get_package_detail(owner: str, repo: str, identifier: str) -> Dict:
    """
    Get detailed package information including download URLs.

    Args:
        owner: Repository owner
        repo: Repository name
        identifier: Package identifier/slug

    Returns:
        Detailed package dictionary
    """
    client = get_packages_api()

    with catch_raise_api_exception():
        data, _, headers = client.packages_read_with_http_info(
            owner=owner, repo=repo, identifier=identifier
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def stream_download(  # noqa: C901
    url: str,
    outfile: str,
    session: requests.Session,
    *,
    headers: Optional[Dict[str, str]] = None,
    overwrite: bool = False,
    quiet: bool = False,
) -> None:
    """
    Stream download a file with progress bar and checksum verification.

    Args:
        url: Download URL
        outfile: Output file path
        session: Requests session to use
        headers: Additional headers for the request
        overwrite: Whether to overwrite existing files
        quiet: Whether to suppress progress output
    """
    # Check if file exists
    if os.path.exists(outfile) and not overwrite:
        raise click.ClickException(
            f"File '{outfile}' already exists. Use --overwrite to replace it."
        )

    # Prepare headers
    request_headers = headers.copy() if headers else {}

    # For Cloudsmith downloads, we need to check what type of auth we have
    auth = None

    # Check if this is a /basic/ endpoint that requires Basic Auth
    is_basic_endpoint = "/basic/" in url

    if is_basic_endpoint:
        # /basic/ endpoints require Basic Auth with API keys
        # SSO Bearer tokens cannot be used directly with Basic Auth
        if "Authorization" in request_headers and request_headers[
            "Authorization"
        ].startswith("Bearer "):
            # SSO Bearer tokens don't work with /basic/ endpoints - need API key
            if not quiet:
                click.echo(
                    "Warning: SSO authentication detected. Private repository downloads require an API key.",
                    err=True,
                )
                click.echo("Options:", err=True)
                click.echo(
                    "  1. Set environment variable: export CLOUDSMITH_API_KEY=your_api_key",
                    err=True,
                )
                click.echo("  2. Use command option: --api-key YOUR_KEY", err=True)
            # Remove Authorization header since it won't work
            request_headers = {
                k: v for k, v in request_headers.items() if k != "Authorization"
            }
        elif "X-Api-Key" in request_headers:
            api_key = request_headers["X-Api-Key"]
            auth = (
                "token",
                api_key,
            )  # Basic auth: (username='token', password=api_key)
            # Remove X-Api-Key header since we're using Basic Auth instead
            request_headers = {
                k: v for k, v in request_headers.items() if k != "X-Api-Key"
            }
    # For public endpoints (like /public/), keep headers as-is

    # Attempt download with configured auth
    try:
        response = session.get(url, headers=request_headers, auth=auth, stream=True)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise click.ClickException(
            f"Failed to download package: HTTP {e.response.status_code}"
        )
    except requests.exceptions.RequestException as e:
        raise click.ClickException(f"Failed to download package: {str(e)}")

    # Get content length for progress bar
    total_size = int(response.headers.get("content-length", 0))

    # Create output directory if needed
    os.makedirs(os.path.dirname(outfile), exist_ok=True)

    # Download with progress bar
    downloaded = 0
    chunk_size = 8192

    with click.open_file(outfile, "wb") as f:
        if not quiet and total_size > 0:
            with click.progressbar(
                length=total_size, label="Downloading"
            ) as progress_bar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress_bar.update(len(chunk))
        else:
            # No progress bar for unknown size or quiet mode
            if not quiet:
                click.echo(f"Downloading to {outfile}...")
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

    if not quiet:
        click.secho(f"✓ Downloaded {_format_size(downloaded)} to {outfile}", fg="green")

    # Verify checksum if available in response headers
    expected_checksum = response.headers.get("etag", "").strip('"')
    if expected_checksum and not quiet:
        if _verify_checksum(outfile, expected_checksum):
            click.secho("✓ Checksum verified", fg="green")
        else:
            click.secho("⚠ Checksum mismatch", fg="yellow", err=True)


def _select_best_package(packages: List[Dict]) -> Dict:
    """Select the best package from multiple matches."""

    # Sort by version (desc) then by upload date (desc)
    def sort_key(pkg):
        version = pkg.get("version", "0")
        uploaded_at = pkg.get("uploaded_at", "")

        # Simple version comparison - split by dots and pad
        version_parts = []
        for part in version.split("."):
            # Extract numeric part, fallback to 0
            try:
                num = int("".join(filter(str.isdigit, part)) or "0")
            except ValueError:
                num = 0
            version_parts.append(num)

        # Pad to 4 parts for consistent comparison
        while len(version_parts) < 4:
            version_parts.append(0)

        return (tuple(version_parts), uploaded_at)

    return sorted(packages, key=sort_key, reverse=True)[0]


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes == 0:
        return "0 B"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0

    return f"{size_bytes:.1f} PB"


def _format_date(date_str):
    """Format date string for display."""
    if not date_str:
        return ""

    # Handle datetime objects
    if hasattr(date_str, "strftime"):
        return date_str.strftime("%Y-%m-%d")

    # Handle string dates - just return first 10 chars (YYYY-MM-DD) for now
    return date_str[:10] if len(date_str) >= 10 else date_str


def _verify_checksum(filepath: str, expected: str) -> bool:
    """Verify file checksum."""
    try:
        # Try MD5 first (most common)
        if len(expected) == 32:
            return utils.calculate_file_md5(filepath) == expected

        # Try SHA1
        if len(expected) == 40:
            sha1_hash = hashlib.sha1()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha1_hash.update(chunk)
            return sha1_hash.hexdigest() == expected

        return False
    except (OSError, ValueError):  # File I/O or hash computation errors
        return False
