"""CLI/Commands - Vulnerabilities."""

import click

from ...core.api.vulnerabilities import get_package_scan_result
from .. import decorators, utils, validators
from ..exceptions import handle_api_exceptions
from .main import main


@main.command()
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.argument(
    "owner_repo_package",
    metavar="OWNER/REPO/PACKAGE",
    callback=validators.validate_owner_repo_package,
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
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --A / --show-assessment

    \b
    # Filter the result by severity
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --severity critical,high

    \b
    # Filter by fixable or non-fixable vulnerabilities
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --fixable / --non-fixable


    """
    owner, repo, slug = owner_repo_package

    context_msg = "Failed to retrieve vulnerability report!"
    with handle_api_exceptions(ctx, opts=opts, context_msg=context_msg):
        with utils.maybe_spinner(opts):
            get_package_scan_result(
                opts=opts,
                owner=owner,
                repo=repo,
                package=slug,
                show_assessment=show_assessment,
                severity_filter=severity_filter,
                fixable=fixable,
            )
