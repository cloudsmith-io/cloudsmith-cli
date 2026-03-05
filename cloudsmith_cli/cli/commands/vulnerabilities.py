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
    help="Show full assessment with vulnerability details.",
)
# @click.option(
#     "--fixable",
#     is_flag=True,
#     help="Show only fixable vulnerabilities.",
# )
@click.option(
    "--severity",
    "severity_filter",
    help="Filter by severities (e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW').",
)
@click.option(
    "--html",
    "html_report",
    required=False,
    is_flag=False,
    flag_value="DEFAULT",
    help="Generate HTML report of the full assessment. Optional specify location to store file. ",
)
@click.pass_context
def vulnerabilities(
    ctx, opts, owner_repo_package, show_assessment, severity_filter, html_report
):
    """
    Retrieve vulnerability results.

    \b
    Usage:
        cloudsmith vulnerabilities myorg/repo/pkg_identifier [flags]

    \b
    Aliases:
        vulnerabilities, vuln


    Examples:

    #Display the vulnerability scan overview
    cloudsmith vulnerabilities myorg/repo/pkg_identifier

    #Display the full vulnerability scan result
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --all

    #Filter the result by severity
    cloudsmith vulnerabilities myorg/repo/pkg_identifier --severity CRITICAL,HIGH


    """

    owner, repo, slug = owner_repo_package

    # Use stderr for messages if output is JSON
    use_stderr = utils.should_use_stderr(opts)

    click.echo("")
    click.echo(
        "Retrieving vulnerability results ... ",
        nl=False,
        err=use_stderr,
    )

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
                html_report=html_report,
                # severity_filter=severity_filter
            )
    # click.secho("OK", fg="green", err=use_stderr)
