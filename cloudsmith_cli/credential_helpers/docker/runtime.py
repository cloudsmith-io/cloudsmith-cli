# Copyright 2026 Cloudsmith Ltd
"""
Docker credential helper runtime.

Transport-light protocol logic for the Docker credential helper protocol.
This module is intentionally free of Click/sys imports so it can be unit-tested
without invoking the CLI machinery.

See: https://github.com/docker/docker-credential-helpers
"""

import json
import logging

from ..common import is_cloudsmith_domain

logger = logging.getLogger(__name__)

_REFUSAL_MESSAGE = (
    "Error: Unable to retrieve credentials. "
    "Provide credentials via the CLOUDSMITH_API_KEY environment variable, "
    "credentials.ini, the system keyring, or an OIDC service. "
    "Verify current authentication with `cloudsmith whoami --verbose`."
)


def get_credentials(server_url, credential=None, api_host=None):
    """
    Get credentials for a Cloudsmith Docker registry.

    Verifies the URL is a Cloudsmith registry (including custom domains)
    and returns credentials if available.

    Args:
        server_url: The Docker registry server URL
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL

    Returns:
        dict: Credentials with 'Username' and 'Secret' keys, or None
    """
    if not credential or not credential.api_key:
        return None

    if not is_cloudsmith_domain(
        server_url,
        api_key=credential.api_key,
        auth_type=getattr(credential, "auth_type", "api_key"),
        api_host=api_host,
    ):
        return None

    return {"Username": "token", "Secret": credential.api_key}


def _execute_get(stdin, credential, api_host) -> tuple[int, str | None, str | None]:
    """Handle the 'get' operation of the Docker credential helper protocol."""
    try:
        server_url = stdin.read().strip()
        if not server_url:
            return (1, None, "Error: No server URL provided on stdin")

        creds = get_credentials(server_url, credential=credential, api_host=api_host)
        if creds is None:
            return (1, None, _REFUSAL_MESSAGE)

        return (0, json.dumps(creds), None)
    except Exception as exc:  # pylint: disable=broad-except
        # Protocol boundary: a credential helper must never crash `docker pull`/`push`.
        # Covers: broken-pipe OSError from stdin.read(), network/SDK errors from
        # get_credentials, and TypeError from json.dumps — all degrade to a clean
        # refusal (exit 1), not a traceback.
        # This is the ONLY intentional broad except in this feature.
        # (Exception does not catch KeyboardInterrupt/SystemExit, which is correct.)
        logger.debug("docker credential-helper get failed: %s", exc, exc_info=True)
        return (1, None, _REFUSAL_MESSAGE)


def execute(
    operation, stdin, credential=None, api_host=None
) -> tuple[int, str | None, str | None]:
    """
    Execute a Docker credential helper protocol operation.

    Args:
        operation: One of 'get', 'store', 'erase', 'list'
        stdin: A file-like object to read the server URL from (for 'get')
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL

    Returns:
        A (exit_code, stdout_text, stderr_text) tuple.  Either text value may
        be None if there is nothing to write to that stream.
    """
    if operation in ("store", "erase"):
        # Drain stdin to keep Docker happy; guard against tty/pipe errors.
        try:
            if not stdin.isatty():
                stdin.read()
        except (OSError, ValueError, AttributeError):
            pass
        return (0, None, None)

    if operation == "list":
        return (0, "{}", None)

    if operation == "get":
        return _execute_get(stdin, credential, api_host)

    return (
        1,
        None,
        f"Error: Unknown operation '{operation}'. "
        "Valid operations: get, store, erase, list",
    )
