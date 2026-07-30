# Copyright 2026 Cloudsmith Ltd
"""
Generic credential helper runtime.

Emits a versioned JSON credential document.
"""

import json
import logging

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

_REFUSAL_MESSAGE = (
    "Error: Unable to retrieve credentials. "
    "Provide credentials via the CLOUDSMITH_API_KEY environment variable, "
    "credentials.ini, the system keyring, or an OIDC service. "
    "Verify current authentication with `cloudsmith whoami --verbose`."
)


def build_response(credential):
    """
    Build the versioned credential document.

    Args:
        credential: Pre-resolved CredentialResult from the provider chain

    Returns:
        dict: The credential document, or None when no credential is available
    """
    if not credential or not credential.api_key:
        return None

    return {
        "version": PROTOCOL_VERSION,
        "username": "token",
        "password": credential.api_key,
    }


def execute(credential=None) -> tuple[int, str | None, str | None]:
    """
    Resolve a credential into a versioned JSON document.

    Args:
        credential: Pre-resolved CredentialResult from the provider chain

    Returns:
        A (exit_code, stdout_text, stderr_text) tuple.  Either text value may
        be None if there is nothing to write to that stream.  The document is
        serialised in one step, so a partial document can never be emitted.
    """
    try:
        response = build_response(credential)
        if response is None:
            return (1, None, _REFUSAL_MESSAGE)

        return (0, json.dumps(response), None)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("generic credential-helper failed: %s", exc, exc_info=True)
        return (1, None, _REFUSAL_MESSAGE)
