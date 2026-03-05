"""API - Vulnerabilities endpoints."""

import click
import cloudsmith_api

from ...cli import utils
from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_vulnerabilities_api():
    """Get the vulnerabilities API client."""
    return get_api_client(cloudsmith_api.VulnerabilitiesApi)


def _print_vulnerabilities_summary_table(opts, data):
    """Print vulnerabilities as a table."""
    severity_keys = {
        "Critical": "critical",
        "High": "high",
        "Medium": "medium",
        "Low": "low",
        "Unknown": "unknown",
    }

    headers = ["Package"]
    headers.extend(severity_keys.keys())

    # Get package name and version for the target label
    package_data = getattr(data, "package", None)
    pkg_name = getattr(package_data, "name", "Unknown")
    pkg_version = getattr(package_data, "version", "Unknown")
    target_label = f"{pkg_name}-{pkg_version}"

    # Initialize aggregate counts
    counts = {v: 0 for v in severity_keys.values()}

    # Parse the scans and aggregate results
    scans = getattr(data, "scans", [])
    for scan in scans:
        results = getattr(scan, "results", [])
        for result in results:
            severity = getattr(result, "severity", "unknown").lower()
            if severity in counts:
                counts[severity] += 1
            else:
                counts["unknown"] += 1

    # Create the single summary row
    row = [target_label]
    for _header, key in severity_keys.items():
        row.append(str(counts[key]))

    rows = [row]

    click.echo()
    click.echo()

    utils.pretty_print_table(
        headers=headers, rows=rows, title="Vulnerabilities Summary"
    )

    click.echo()
    click.echo(f"Total Vulnerabilities: {getattr(data, 'num_vulnerabilities', 0)}")
    click.echo()


def get_package_scan_identifier(owner, repo, package):
    """Get the scan identifier using the package identifier"""
    client = get_vulnerabilities_api()

    with catch_raise_api_exception():
        data, _, headers = client.vulnerabilities_package_list_with_http_info(
            owner=owner, repo=repo, package=package
        )

    ratelimits.maybe_rate_limit(client, headers)

    return data[0].identifier


def get_package_scan_result(opts, owner, repo, package, show_assessment):
    """Get the package vulnerability scan result."""
    client = get_vulnerabilities_api()

    with catch_raise_api_exception():
        scan_identifier = get_package_scan_identifier(
            owner=owner, repo=repo, package=package
        )

    with catch_raise_api_exception():
        data, _, headers = client.vulnerabilities_read_with_http_info(
            owner=owner, repo=repo, package=package, identifier=scan_identifier
        )

    ratelimits.maybe_rate_limit(client, headers)

    if utils.maybe_print_as_json(opts, data):
        return

    _print_vulnerabilities_summary_table(opts, data)

    if show_assessment:
        click.echo(f"{data}")
