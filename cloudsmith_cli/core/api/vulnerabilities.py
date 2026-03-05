"""API - Vulnerabilities endpoints."""

import datetime
import html

import click
import cloudsmith_api

from ...cli import utils
from .. import ratelimits
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_vulnerabilities_api():
    """Get the vulnerabilities API client."""
    return get_api_client(cloudsmith_api.VulnerabilitiesApi)


def _generate_html_report(data, owner, repo):
    """Generate an HTML vulnerability report."""
    # Data Extraction
    package_data = getattr(data, "package", None)
    pkg_name = getattr(package_data, "name", "Unknown")
    pkg_version = getattr(package_data, "version", "Unknown")

    target_repo = f"{owner}/{repo}"
    scan_time = datetime.datetime.utcnow().strftime("%B %d, %Y • %H:%M UTC")

    # Calculate Summary Counts
    severity_keys = ["critical", "high", "medium", "low"]
    counts = {k: 0 for k in severity_keys}

    rows_html = ""
    scans = getattr(data, "scans", [])

    for scan in scans:
        results = getattr(scan, "results", [])
        for result in results:
            # Stats
            severity_raw = getattr(result, "severity", "unknown").lower()
            if severity_raw in counts:
                counts[severity_raw] += 1

            # Row Data
            severity_display = (
                severity_raw.upper() if severity_raw in counts else "UNKNOWN"
            )
            # Attempt to find common attribute names for vulnerability details
            vuln_id = str(
                getattr(
                    result, "vulnerability_id", getattr(result, "identifier", "Unknown")
                )
            )
            lib_name = str(getattr(result, "package_name", pkg_name))
            lib_version = str(getattr(result, "package_version", pkg_version))
            # Try to populate fixed version if available
            fixed_version = getattr(
                result, "fix_version", getattr(result, "fixed_version", "")
            )

            fixed_ver_html = (
                f'<span class="fixed-version">{html.escape(str(fixed_version))}</span>'
                if fixed_version
                else "-"
            )

            # Append Row
            rows_html += f"""
            <tr>
                <td><span class="badge badge-{severity_display}">{severity_display.title()}</span></td>
                <td><a href="#" class="cve-link">{html.escape(vuln_id)}</a></td>
                <td><strong>{html.escape(lib_name)}</strong></td>
                <td>{html.escape(lib_version)}</td>
                <td>{fixed_ver_html}</td>
            </tr>
            """

    # Template Construction
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloudsmith Vulnerability Report</title>
    <style>
        :root {{
            --cs-blue: #0366d6;
            --cs-dark: #24292e;
            --CRITICAL: #d73a49;
            --HIGH: #f66a0a;
            --MEDIUM: #fb8c00;
            --LOW: #6a737d;
            --bg-light: #f6f8fa;
            --success: #28a745;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: var(--cs-dark);
            background-color: var(--bg-light);
            margin: 0;
            padding: 40px;
        }}

        .container {{
            max-width: 1000px;
            margin: auto;
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.05);
            border: 1px solid #e1e4e8;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid var(--bg-light);
            padding-bottom: 25px;
            margin-bottom: 30px;
        }}

        .logo-area h1 {{
            margin: 0;
            color: var(--cs-blue);
            font-size: 24px;
            letter-spacing: -0.5px;
        }}

        .logo-area p {{
            margin: 5px 0 0 0;
            color: #586069;
            font-size: 14px;
        }}

        .meta-info {{
            text-align: right;
            font-size: 13px;
            color: #6a737d;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 35px;
        }}

        .summary-card {{
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            color: white;
        }}

        .summary-card.crit {{ background-color: var(--CRITICAL); }}
        .summary-card.high {{ background-color: var(--HIGH); }}
        .summary-card.med {{ background-color: var(--MEDIUM); }}
        .summary-card.low {{ background-color: var(--LOW); }}

        .summary-card .count {{
            display: block;
            font-size: 28px;
            font-weight: 800;
        }}

        .summary-card .label {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            opacity: 0.9;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}

        th {{
            text-align: left;
            background: #fafbfc;
            padding: 15px;
            font-size: 12px;
            color: #586069;
            text-transform: uppercase;
            border-bottom: 2px solid #e1e4e8;
        }}

        td {{
            padding: 15px;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
            vertical-align: middle;
        }}

        tr:hover {{
            background-color: #fcfcfc;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}

        .badge-CRITICAL {{ background: #ffdce0; color: #af1b2b; }}
        .badge-HIGH {{ background: #ffe3d2; color: #bc4c00; }}
        .badge-MEDIUM {{ background: #fff5b1; color: #735c0f; }}
        .badge-LOW {{ background: #e1e4e8; color: #444d56; }}
        .badge-UNKNOWN {{ background: #e1e4e8; color: #444d56; }}

        .cve-link {{
            font-weight: 600;
            color: var(--cs-blue);
            text-decoration: none;
        }}

        .fixed-version {{
            color: var(--success);
            font-weight: 600;
            background: #f0fff4;
            padding: 2px 6px;
            border-radius: 4px;
        }}

        footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            text-align: center;
            font-size: 12px;
            color: #959da5;
        }}
    </style>
</head>
<body>

<div class="container">
    <header>
        <div class="logo-area">
            <h1>Cloudsmith Security Scan</h1>
            <p>Repository: <strong>{html.escape(target_repo)}</strong></p>
            <p>Package: <strong>{html.escape(pkg_name)}</strong></p>
            <p>Version: <strong>{html.escape(pkg_name)}</strong></p>
        </div>
        <div class="meta-info">
            Generated by Cloudsmith CLI<br>
            <strong>{scan_time}</strong>
        </div>
    </header>

    <div class="summary-grid">
        <div class="summary-card crit">
            <span class="count">{counts['critical']}</span>
            <span class="label">Critical</span>
        </div>
        <div class="summary-card high">
            <span class="count">{counts['high']}</span>
            <span class="label">High</span>
        </div>
        <div class="summary-card med">
            <span class="count">{counts['medium']}</span>
            <span class="label">Medium</span>
        </div>
        <div class="summary-card low">
            <span class="count">{counts['low']}</span>
            <span class="label">Low</span>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th style="width: 15%;">Severity</th>
                <th style="width: 20%;">Identifier</th>
                <th style="width: 25%;">Package</th>
                <th style="width: 20%;">Installed</th>
                <th style="width: 20%;">Fixed Version</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <footer>
        &copy; {datetime.datetime.now().year} Cloudsmith Inc. • <a href="https://cloudsmith.io" style="color: inherit;">Visit Dashboard</a> • Be Secure. Be Sure.
    </footer>
</div>

</body>
</html>
    """

    filename = f"vuln-report-{pkg_name}-{pkg_version}.html".replace("/", "_")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    click.echo(f"HTML Report generated: {filename}", err=True)


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


def get_package_scan_result(
    opts, owner, repo, package, show_assessment, severity_filter, html_report
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

    if severity_filter:
        allowed_severities = [s.strip().lower() for s in severity_filter.split(",")]

        # Filter the results inside the data object
        scans = getattr(data, "scans", [])
        total_filtered_vulns = 0

        for scan in scans:
            results = getattr(scan, "results", [])
            filtered_results = [
                res
                for res in results
                if getattr(res, "severity", "unknown").lower() in allowed_severities
            ]
            # update the scan object with filtered results
            scan.results = filtered_results
            total_filtered_vulns += len(filtered_results)

        # Update the total count on the main data object
        data.num_vulnerabilities = total_filtered_vulns

    if html_report:
        _generate_html_report(data, owner, repo)

    if utils.maybe_print_as_json(opts, data):
        return

    _print_vulnerabilities_summary_table(opts, data)

    if show_assessment:
        click.echo(f"{data}")
