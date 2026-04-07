"""API - Vulnerabilities endpoints."""

import click
import cloudsmith_api
from rich.console import Console
from rich.table import Table

from ...cli import utils
from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client

# Severity color mapping for consistent styling
SEVERITY_COLORS = {
    "critical": "red",
    "high": "bright_red",
    "medium": "yellow",
    "low": "blue",
    "unknown": "dim white",
}


def get_vulnerabilities_api():
    """Get the vulnerabilities API client."""
    return get_api_client(cloudsmith_api.VulnerabilitiesApi)


def _colorize_count(count, severity_key):
    """Return a rich-styled count string, colored only when count > 0."""
    if count > 0:
        color = SEVERITY_COLORS.get(severity_key, "white")
        return f"[{color}]{count}[/{color}]"
    return f"[dim]{count}[/dim]"


def _print_vulnerabilities_summary_table(data, severity_filter, total_filtered_vulns):
    """Print vulnerabilities as a color-coded table."""

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

    # Build the rich table
    console = Console()
    table = Table(
        title="Vulnerabilities Summary",
        show_header=True,
        header_style="bold",
        show_lines=True,
        border_style="bright_black",
        padding=(0, 1),
    )

    table.add_column("Package", justify="left", style="cyan", no_wrap=True)
    for display_name, sev_key in severity_keys.items():
        color = SEVERITY_COLORS.get(sev_key, "white")
        table.add_column(display_name, justify="center", header_style=f"bold {color}")
    table.add_column("Total", justify="center", header_style="bold white")

    # Build the row
    row_total = 0
    cells = [target_label]
    for _display, sev_key in severity_keys.items():
        count = counts.get(sev_key, 0)
        cells.append(_colorize_count(count, sev_key))
        row_total += count
    total_style = "[bold red]" if row_total > 0 else "[dim]"
    cells.append(f"{total_style}{row_total}[/]")
    table.add_row(*cells)

    console.print()
    console.print(table)

    if severity_filter:
        console.print(
            f"\nFiltered Vulnerabilities: [bold]{total_filtered_vulns}[/bold]\n"
        )
    else:
        console.print(f"\nTotal Vulnerabilities: [bold]{row_total}[/bold]\n")


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

    if not data:
        return None

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
