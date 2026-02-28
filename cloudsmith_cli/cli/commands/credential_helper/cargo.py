"""
Cargo credential helper command.

Implements credential retrieval for Cargo registries hosted on Cloudsmith.

See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html
"""

import json
import sys

import click

from ....credential_helpers.cargo import get_credentials


@click.command()
@click.option(
    "--cargo-plugin",
    is_flag=True,
    default=False,
    help="Run in Cargo credential provider plugin mode (JSON-line protocol).",
)
@click.argument("index_url", required=False, default=None)
def cargo(cargo_plugin, index_url):
    """
    Cargo credential helper for Cloudsmith registries.

    Returns credentials as a Bearer token for Cargo sparse registries.

    If --cargo-plugin is passed, runs the full Cargo credential provider
    JSON-line protocol (hello handshake, request/response). This is used
    by the cargo-credential-cloudsmith wrapper binary.

    If INDEX_URL is provided as an argument, uses it directly.
    Otherwise reads from stdin.

    Examples:
        # Direct usage
        $ cloudsmith credential-helper cargo sparse+https://cargo.cloudsmith.io/org/repo/
        Bearer eyJ0eXAiOiJKV1Qi...

        # Via wrapper (called by Cargo)
        $ cargo-credential-cloudsmith --cargo-plugin

    Environment variables:
        CLOUDSMITH_API_KEY: API key for authentication (optional)
        CLOUDSMITH_ORG: Organization slug (required for OIDC)
        CLOUDSMITH_SERVICE_SLUG: Service account slug (required for OIDC)
    """
    if cargo_plugin:
        _run_cargo_plugin()
        return

    try:
        if not index_url:
            index_url = sys.stdin.read().strip()

        if not index_url:
            click.echo("Error: No index URL provided", err=True)
            sys.exit(1)

        token = get_credentials(index_url, debug=False)

        if not token:
            click.echo(
                "Error: Unable to retrieve credentials. "
                "Set CLOUDSMITH_API_KEY or configure OIDC.",
                err=True,
            )
            sys.exit(1)

        click.echo(json.dumps({"token": f"Bearer {token}"}))

    except Exception as e:  # pylint: disable=broad-exception-caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _run_cargo_plugin():
    """
    Run the full Cargo credential provider JSON-line protocol.

    See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html
    """
    hello = {"v": [1]}
    sys.stdout.write(json.dumps(hello) + "\n")
    sys.stdout.flush()

    try:
        line = sys.stdin.readline()
        if not line:
            sys.exit(0)

        request = json.loads(line)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    kind = request.get("kind", "")
    registry = request.get("registry", {})
    index_url = registry.get("index-url", "")

    if kind == "get":
        _handle_get(index_url)
    elif kind in ("login", "logout"):
        _handle_unsupported(kind)
    else:
        _write_error("operation-not-supported", f"Unknown operation: {kind}")


def _handle_get(index_url):
    """Handle a 'get' request from Cargo."""
    token = get_credentials(index_url)
    if not token:
        _write_error(
            "not-found",
            "No credentials available. Set CLOUDSMITH_API_KEY or configure OIDC.",
        )
        return

    response = {
        "Ok": {
            "kind": "get",
            "token": f"Bearer {token}",
            "cache": "session",
            "operation_independent": True,
        }
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _handle_unsupported(kind):
    """Handle unsupported operations (login/logout)."""
    _write_error(
        "operation-not-supported",
        f"Operation '{kind}' is not supported. "
        "Credentials are managed by the Cloudsmith credential chain.",
    )


def _write_error(kind, message):
    """Write an error response in Cargo JSON-line format."""
    response = {"Err": {"kind": kind, "message": message}}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
