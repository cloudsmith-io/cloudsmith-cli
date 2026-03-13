"""CLI/Commands - Vulnerabilities."""

import click

from ...core.api.packages import list_packages
from ...core.api.vulnerabilities import (
    _print_vulnerabilities_assessment_table,
    _print_vulnerabilities_summary_table,
    get_package_scan_result,
)
from .. import decorators, utils, validators
from .main import main


def get_packages_in_repo(opts, owner, repo):
    """Get list of packages in a repository. Returns list of package identifiers."""
    packages, _ = list_packages(
        opts=opts, owner=owner, repo=repo, query=None, sort=None
    )

    return [pkg["slug_perm"] for pkg in packages]


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
    default=None,  # Changed to allow None (Show All) vs True/False
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

    if repo_summary and show_assessment:
        click.echo("Show full assessment is not supported for the repo level summary.")

    if slug is None:
        slugs = get_packages_in_repo(opts, owner, repo)
    else:
        slugs = [slug]

    for slug in slugs:
        total_filtered_vulns = 0
        data = None

        # Manually handle exceptions to skip packages (e.g. no scan found) instead of exiting
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
            click.secho(
                f"Warning: Failed to retrieve vulnerability report for {slug}: {exc}",
                fg="yellow",
                err=use_stderr,
            )
            continue

        if not data:
            continue

        click.secho("OK", fg="green", err=use_stderr)

        # Filter results if severity or fixable flags are active
        if severity_filter or fixable is not None:
            scans = getattr(data, "scans", [])

            allowed_severities = (
                [s.strip().lower() for s in severity_filter.split(",")]
                if severity_filter
                else None
            )

            for scan in scans:
                results = getattr(scan, "results", [])

                # 1. Filter by Severity
                if allowed_severities:
                    results = [
                        res
                        for res in results
                        if getattr(res, "severity", "unknown").lower()
                        in allowed_severities
                    ]

                # 2. Filter by Fixable Status
                # fixable=True: Keep only if has fix_version
                # fixable=False: Keep only if NO fix_version
                if fixable is not None:
                    results = [
                        res
                        for res in results
                        if bool(
                            getattr(
                                res, "fix_version", getattr(res, "fixed_version", None)
                            )
                        )
                        is fixable
                    ]

                scan.results = results
                total_filtered_vulns += len(results)

        if utils.maybe_print_as_json(opts, data):
            return

        _print_vulnerabilities_summary_table(
            data, severity_filter, total_filtered_vulns
        )

        if show_assessment:
            if not repo_summary:
                _print_vulnerabilities_assessment_table(data, severity_filter)
