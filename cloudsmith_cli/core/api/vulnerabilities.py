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


def _print_vulnerabilities_summary_table(data, severity_filter, total_filtered_vulns):
    """Print vulnerabilities as a table."""

    severity_keys = {
        "Critical": "critical",
        "High": "high",
        "Medium": "medium",
        "Low": "low",
        "Unknown": "unknown",
    }

    if severity_filter:
        allowed = [s.strip().lower() for s in severity_filter.split(",")]
        severity_keys = {k: v for k, v in severity_keys.items() if v in allowed}

    headers = [{"header": "Package", "justify": "left", "style": "cyan"}]
    for key in severity_keys.keys():
        headers.append({"header": key, "justify": "center", "style": "white"})

    # Get package name and version for the target label
    pkg_data = getattr(data, "package", None)
    pkg_name = getattr(pkg_data, "name", "Unknown")
    pkg_version = getattr(pkg_data, "version", "Unknown")
    target_label = f"{pkg_name}:{pkg_version}"

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
            elif "unknown" in counts:
                counts["unknown"] += 1

    # Create the single summary row
    row = [target_label]
    for _header, key in severity_keys.items():
        row.append(str(counts[key]))

    rows = [row]

    click.echo()
    click.echo()

    utils.rich_print_table(headers=headers, rows=rows, title="Vulnerabilities Summary")

    if severity_filter:
        filters = severity_filter.upper()
        click.echo(
            f"\nTotal Vulnerabilities: {getattr(data, 'num_vulnerabilities', 0)}"
        )
        click.echo(f"\nTotal {filters} Vulnerabilities: {total_filtered_vulns}")
    else:
        click.echo(
            f"\nTotal Vulnerabilities: {getattr(data, 'num_vulnerabilities', 0)}"
        )
    click.echo()


def _print_vulnerabilities_assessment_table(data, severity_filter=None):
    """Print vulnerabilities assessment as a table."""

    # Group vulnerabilities by package
    grouped_vulns = {}

    allowed_severities = None
    if severity_filter:
        allowed_severities = [s.strip().lower() for s in severity_filter.split(",")]

    # Get top level package info as fallback
    pkg_data = getattr(data, "package", None)
    top_pkg_name = getattr(pkg_data, "name", "Unknown")

    # Get scan data
    scans = getattr(data, "scans", [])
    for scan in scans:
        results = getattr(scan, "results", [])
        for result in results:
            # Filter by severity if requested
            if allowed_severities:
                severity = getattr(result, "severity", "unknown").lower()
                if severity not in allowed_severities:
                    continue

            pkg_name = getattr(result, "package_name", top_pkg_name)
            if pkg_name not in grouped_vulns:
                grouped_vulns[pkg_name] = []
            grouped_vulns[pkg_name].append(result)

    if not grouped_vulns:
        click.echo("\nNo vulnerabilities found matching criteria.")
        return

    # Severity mapping for sorting
    sev_map = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}

    # Iterate through sorted packages
    for pkg_name in sorted(grouped_vulns.keys()):
        vulns = grouped_vulns[pkg_name]

        # Sort vulns by severity (Critical first)
        vulns.sort(
            key=lambda r: sev_map.get(getattr(r, "severity", "unknown").lower(), 99)
        )

        rows = []
        for result in vulns:
            # Severity
            severity = getattr(result, "severity", "Unknown").title()
            severity_style = "white"
            s = severity.lower()
            if s == "critical":
                severity_style = "red bold"
            elif s == "high":
                severity_style = "red"
            elif s == "medium":
                severity_style = "yellow"
            elif s == "low":
                severity_style = "blue"

            # ID
            vuln_id = getattr(
                result, "vulnerability_id", getattr(result, "identifier", "Unknown")
            )

            # Affected Version
            affected_raw = getattr(
                result, "affected_version", getattr(result, "affected_version", None)
            )
            if hasattr(affected_raw, "version"):
                aff_version = affected_raw.version
                affected_operator = affected_raw.operator
                affected_version = f"{affected_operator} {aff_version}"
            else:
                affected_version = str(affected_raw) if affected_raw else "-"

            # Fixed Version
            fixed_raw = getattr(
                result, "fix_version", getattr(result, "fixed_version", None)
            )
            if hasattr(fixed_raw, "version"):
                fix_version = fixed_raw.version
                fixed_operator = fixed_raw.operator
                fixed_version = f"{fixed_operator} {fix_version}"
            else:
                fixed_version = str(fixed_raw) if fixed_raw else "-"

            # Title / Description
            title = getattr(result, "title", "")

            rows.append(
                [
                    f"[{severity_style}]{severity}[/{severity_style}]",
                    vuln_id,
                    affected_version,
                    fixed_version,
                    title,
                ]
            )

        click.echo()
        utils.rich_print_table(
            headers=[
                "Severity",
                "Vulnerability",
                "Affected Version",
                "Fixed Version",
                "Title",
            ],
            rows=rows,
            title=f"Package: {pkg_name}",
            show_lines=True,
        )
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


def get_package_scan_result(
    opts, owner, repo, package, show_assessment, fixable, severity_filter
):
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

    return data
