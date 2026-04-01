"""CLI/Commands - Vulnerabilities."""

# Copyright 2026 Cloudsmith Ltd

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
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
    """Get all packages in a repository, paginating through all pages."""
    all_packages = []
    page = 1
    page_size = 100  # fetch in larger batches for efficiency

    try:
        while True:
            packages, page_info = list_packages(
                opts=opts,
                owner=owner,
                repo=repo,
                query=None,
                sort=None,
                page=page,
                page_size=page_size,
            )

            if packages:
                all_packages.extend(packages)

            # No page info means single page or no results
            if not page_info:
                break

            current_page = getattr(page_info, "page", page)
            total_pages = getattr(page_info, "page_total", 1)

            if current_page >= total_pages:
                break

            page += 1

    except Exception as exc:
        raise click.ClickException(
            f"Failed to list packages for '{owner}/{repo}'. "
            f"Please check the owner and repository names are correct. "
            f"Detail: {exc}"
        ) from exc

    if not all_packages:
        raise click.ClickException(
            f"No packages found in '{owner}/{repo}'. "
            f"The repository may be empty, or the owner/repo names may be incorrect."
        )

    return [
        (pkg["slug_perm"], pkg.get("name", pkg["slug_perm"]), pkg.get("version", ""))
        for pkg in all_packages
    ]


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
    num_sev_cols = len(severity_keys)

    for label, counts, status in package_rows:
        cells = [label]
        if status == "no_scan":
            cells.append("[dim italic]Security scan not supported[/dim italic]")
            cells.extend([""] * (num_sev_cols - 1))
            cells.append("")
        elif status == "no_issues_found":
            cells.append("[bold green]No issues found[/bold green]")
            cells.extend([""] * (num_sev_cols - 1))
            cells.append("")
        else:
            row_total = 0
            for _display, sev_key in severity_keys.items():
                count = counts.get(sev_key, 0)
                cells.append(_colorize_count(count, sev_key))
                row_total += count
            total_style = "[bold red]" if row_total > 0 else "[dim]"
            cells.append(f"{total_style}{row_total}[/]")
            grand_total += row_total
        table.add_row(*cells)

    console.print()
    console.print(table)
    console.print(f"\nTotal Vulnerabilities: [bold]{grand_total}[/bold]\n")


def _collect_repo_scan_data(opts, owner, repo, slugs, severity_filter, fixable):
    """Silently collect scan data for all packages with a progress bar.

    Returns list of (slug, label, counts, status) tuples where status is one of
    "vulnerable", "safe", or "no_scan". Sorted: vulnerable (by count desc),
    then safe, then no_scan.
    """
    rows = []
    console = Console(stderr=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning packages...", total=len(slugs))

        for slug, pkg_name_fallback, pkg_version_fallback in slugs:
            progress.update(task, description=f"Processing {slug}...")
            fallback_label = (
                f"{pkg_name_fallback}:{pkg_version_fallback}"
                if pkg_version_fallback
                else pkg_name_fallback
            )

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
                rows.append((slug, fallback_label, {}, "no_scan"))
                progress.advance(task)
                continue

            # Build label from scan response metadata, fall back to list_packages data
            pkg_data = getattr(data, "package", None) if data else None
            pkg_name = (
                getattr(pkg_data, "name", pkg_name_fallback)
                if pkg_data
                else pkg_name_fallback
            )
            pkg_version = (
                getattr(pkg_data, "version", pkg_version_fallback)
                if pkg_data
                else pkg_version_fallback
            )
            label = f"{pkg_name}:{pkg_version}" if pkg_version else pkg_name

            if not data or not _has_scan_results(data):
                rows.append((slug, label, {}, "no_scan"))
                progress.advance(task)
                continue

            # Apply filters if active
            if severity_filter or fixable is not None:
                _apply_filters(data, severity_filter, fixable)

            counts = _aggregate_severity_counts(data, severity_filter)

            if sum(counts.values()) > 0:
                rows.append((slug, label, counts, "vulnerable"))
            else:
                rows.append((slug, label, counts, "no_issues_found"))

            progress.advance(task)

    # Sort: vulnerable first (by total desc), then safe, then no_scan
    vulnerable = [r for r in rows if r[3] == "vulnerable"]
    vulnerable.sort(key=lambda r: sum(r[2].values()), reverse=True)
    safe = [r for r in rows if r[3] == "no_issues_found"]
    no_scan = [r for r in rows if r[3] == "no_scan"]

    return vulnerable + safe + no_scan


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
        return

    # Repo summary mode: collect with progress bar, then output once
    if repo_summary:
        slugs = get_packages_in_repo(opts, owner, repo)

        repo_summary_rows = _collect_repo_scan_data(
            opts, owner, repo, slugs, severity_filter, fixable
        )

        if not repo_summary_rows:
            click.secho(
                f"No scan data could be retrieved for any packages "
                f"in '{owner}/{repo}'.",
                fg="yellow",
                err=use_stderr,
            )
            return

        json_output = {
            "owner": owner,
            "repository": repo,
            "packages": [
                {
                    "slug_perm": slug_perm,
                    "package": label,
                    "status": status,
                    "vulnerabilities": counts,
                }
                for slug_perm, label, counts, status in repo_summary_rows
            ],
        }

        if utils.maybe_print_as_json(opts, json_output):
            return

        # Table only needs label, counts, and status
        _print_repo_summary_table(
            [(label, counts, status) for _, label, counts, status in repo_summary_rows],
            severity_filter,
        )
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
