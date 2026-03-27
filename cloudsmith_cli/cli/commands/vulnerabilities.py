"""CLI/Commands - Vulnerabilities."""

# Copyright 2026 Cloudsmith Ltd

import click
from rich.console import Console
from rich.table import Table

from ...core.api.packages import list_packages
from ...core.api.vulnerabilities import (
    _print_vulnerabilities_assessment_table,
    _print_vulnerabilities_summary_table,
    get_package_scan_result,
)
from .. import decorators, utils, validators
from .main import main


def get_packages_in_repo(opts, owner, repo):
    """Get list of packages in a repository."""
    try:
        packages, _ = list_packages(
            opts=opts, owner=owner, repo=repo, query=None, sort=None
        )
    except Exception as exc:
        raise click.ClickException(
            f"Failed to list packages for '{owner}/{repo}'. "
            f"Please check the owner and repository names are correct. "
            f"Detail: {exc}"
        ) from exc

    if not packages:
        raise click.ClickException(
            f"No packages found in '{owner}/{repo}'. "
            f"The repository may be empty, or the owner/repo names may be incorrect."
        )

    return [pkg["slug_perm"] for pkg in packages]


def _has_scan_results(data):
    """Check whether scan data contains actual scan results."""
    scans = getattr(data, "scans", None)
    if scans is None:
        return False
    return len(scans) > 0


def _has_vulnerabilities(data):
    """Check whether scan data contains any vulnerability results."""
    scans = getattr(data, "scans", [])
    return any(getattr(scan, "results", []) for scan in scans)


def _aggregate_severity_counts(data, severity_filter=None):
    """Aggregate vulnerability counts by severity for a single package scan."""
    severity_keys = ["critical", "high", "medium", "low", "unknown"]

    if severity_filter:
        allowed = [s.strip().lower() for s in severity_filter.split(",")]
        severity_keys = [k for k in severity_keys if k in allowed]

    counts = {k: 0 for k in severity_keys}

    scans = getattr(data, "scans", [])
    for scan in scans:
        results = getattr(scan, "results", [])
        for result in results:
            severity = getattr(result, "severity", "unknown").lower()
            if severity in counts:
                counts[severity] += 1
            elif "unknown" in counts:
                counts["unknown"] += 1

    return counts


def _apply_filters(data, severity_filter, fixable):
    """Apply severity and fixable filters to scan results in-place. Returns filtered count."""
    total_filtered = 0
    scans = getattr(data, "scans", [])

    allowed_severities = (
        [s.strip().lower() for s in severity_filter.split(",")]
        if severity_filter
        else None
    )

    for scan in scans:
        results = getattr(scan, "results", [])

        if allowed_severities:
            results = [
                res
                for res in results
                if getattr(res, "severity", "unknown").lower() in allowed_severities
            ]

        if fixable is not None:
            results = [
                res
                for res in results
                if bool(
                    getattr(res, "fix_version", getattr(res, "fixed_version", None))
                )
                is fixable
            ]

        scan.results = results
        total_filtered += len(results)

    return total_filtered


# Severity color mapping for consistent styling
SEVERITY_COLORS = {
    "critical": "red",
    "high": "bright_red",
    "medium": "yellow",
    "low": "blue",
    "unknown": "dim white",
}


def _colorize_count(count, severity_key):
    """Return a rich-styled count string, colored only when count > 0."""
    if count > 0:
        color = SEVERITY_COLORS.get(severity_key, "white")
        return f"[{color}]{count}[/{color}]"
    return f"[dim]{count}[/dim]"


def _print_repo_summary_table(package_rows, severity_filter=None):
    """Print a single combined summary table for all packages in a repo."""
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

    console = Console()
    table = Table(
        title="Repository Vulnerabilities Summary",
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

    grand_total = 0

    for label, counts in package_rows:
        row_total = 0
        cells = [label]
        for _display, sev_key in severity_keys.items():
            count = counts.get(sev_key, 0)
            cells.append(_colorize_count(count, sev_key))
            row_total += count
        total_style = "[bold red]" if row_total > 0 else "[dim]"
        cells.append(f"{total_style}{row_total}[/]")
        table.add_row(*cells)
        grand_total += row_total

    console.print()
    console.print(table)
    console.print(f"\nTotal Vulnerabilities: [bold]{grand_total}[/bold]\n")


def _collect_repo_scan_data(opts, owner, repo, slugs, severity_filter, fixable):
    """Silently collect scan data for all packages. Returns list of (label, counts) tuples."""
    rows = []

    for slug in slugs:
        try:
            data = get_package_scan_result(
                opts=opts,
                owner=owner,
                repo=repo,
                package=slug,
                show_assessment=False,
                severity_filter=severity_filter,
                fixable=fixable,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            continue

        # Skip packages with no scan data
        if not data or not _has_scan_results(data):
            continue

        # Apply filters if active
        if severity_filter or fixable is not None:
            _apply_filters(data, severity_filter, fixable)

        # Build label from package metadata
        pkg_data = getattr(data, "package", None)
        pkg_name = getattr(pkg_data, "name", slug)
        pkg_version = getattr(pkg_data, "version", "")
        label = f"{pkg_name}:{pkg_version}" if pkg_version else pkg_name

        counts = _aggregate_severity_counts(data, severity_filter)
        rows.append((label, counts))

    # Sort by total vulnerability count descending
    rows.sort(key=lambda row: sum(row[1].values()), reverse=True)

    return rows


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO or OWNER/REPO/PACKAGE",
    callback=validators.validate_required_owner_repo_optional_slug_perm,
)
@click.option(
    "-A",
    "--show-assessment",
    is_flag=True,
    help="Show assessment with vulnerability details.",
)
@click.option(
    "--fixable/--non-fixable",
    is_flag=True,
    default=None,  # allow None (show all) vs True/False
    help="Filter by fixable status (only fixable vs only non-fixable).",
)
@click.option(
    "--severity",
    "severity_filter",
    help="Filter by severities (e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW').",
)
@click.pass_context
def vulnerabilities(
    ctx, opts, owner_repo_package, show_assessment, fixable, severity_filter
):
    """
    Retrieve vulnerability scan results for a package.

    \b
    Usage:
        cloudsmith vulnerabilities myorg/repo/pkg_identifier [flags]

    \b
    Aliases:
        vulnerabilities, vuln

    Examples:

    \b
    # Display the vulnerability summary
    cloudsmith vulnerabilities myorg/repo/pkg_identifier

    \b
    # Display detailed vulnerability assessment
    cloudsmith vulnerabilities myorg/repo/pkg_identifier -A / --show-assessment

    \b
    # Filter the result by severity
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --severity critical,high

    \b
    # Filter by fixable or non-fixable vulnerabilities
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --fixable / --non-fixable
    """
    use_stderr = utils.should_use_stderr(opts)
    repo_summary = False

    if len(owner_repo_package) == 3:
        owner, repo, slug = owner_repo_package
    else:
        owner, repo = owner_repo_package
        slug = None
        repo_summary = True

    if not owner or not repo:
        raise click.ClickException(
            "Both owner and repository must be specified (e.g., 'myorg/myrepo')."
        )

    if repo_summary and show_assessment:
        click.secho(
            "Show full assessment is not supported for the repo level summary.",
            fg="yellow",
            err=use_stderr,
        )

    # Repo summary mode: collect everything silently, then output once
    if repo_summary:
        slugs = get_packages_in_repo(opts, owner, repo)

        with utils.maybe_spinner(opts):
            repo_summary_rows = _collect_repo_scan_data(
                opts, owner, repo, slugs, severity_filter, fixable
            )

        if not repo_summary_rows:
            click.secho(
                f"No vulnerability scan results found for any packages "
                f"in '{owner}/{repo}'.",
                fg="yellow",
                err=use_stderr,
            )
            return

        if utils.maybe_print_as_json(opts, repo_summary_rows):
            return

        _print_repo_summary_table(repo_summary_rows, severity_filter)
        return

    # Single-package mode
    slugs = [slug]
    data = None

    try:
        with utils.maybe_spinner(opts):
            data = get_package_scan_result(
                opts=opts,
                owner=owner,
                repo=repo,
                package=slug,
                show_assessment=show_assessment,
                severity_filter=severity_filter,
                fixable=fixable,
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise click.ClickException(
            f"Failed to retrieve vulnerability report for "
            f"'{owner}/{repo}/{slug}': {exc}"
        ) from exc

    if not data or not _has_scan_results(data):
        click.secho(
            f"No scan results found for '{owner}/{repo}/{slug}'. "
            f"The package may not have been scanned yet or is not supported.",
            fg="yellow",
            err=use_stderr,
        )
        return

    total_filtered_vulns = 0

    if severity_filter or fixable is not None:
        total_filtered_vulns = _apply_filters(data, severity_filter, fixable)

    if not _has_vulnerabilities(data) and total_filtered_vulns == 0:
        click.secho(
            f"Scan completed for '{owner}/{repo}/{slug}': "
            f"no vulnerabilities detected.",
            fg="green",
            err=use_stderr,
        )
    else:
        click.secho("OK", fg="green", err=use_stderr)

    if total_filtered_vulns == 0 and (severity_filter or fixable is not None):
        click.secho(
            f"Scan completed for '{owner}/{repo}/{slug}' but no "
            f"vulnerabilities matched the applied filters.",
            fg="yellow",
            err=use_stderr,
        )

    if utils.maybe_print_as_json(opts, data):
        return

    _print_vulnerabilities_summary_table(data, severity_filter, total_filtered_vulns)

    if show_assessment:
        _print_vulnerabilities_assessment_table(data, severity_filter)
