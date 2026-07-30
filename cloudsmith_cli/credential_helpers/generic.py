# Copyright 2026 Cloudsmith Ltd
"""
Generic (package-manager-neutral) credential helper runtime.

Emits a versioned JSON credential document for external consumers such as the
``cloudsmith-keyring`` keyring backend, which shells out to the CLI rather than
importing it (see ENG-13681).

This module is intentionally free of Click/sys imports so it can be unit-tested
without invoking the CLI machinery.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Bump only for a breaking change to the document shape. Consumers are expected
# to refuse a version they do not recognise.
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
        # Protocol boundary: this command is invoked as a subprocess by pip and
        # twine via the keyring backend, which must degrade silently rather than
        # break the install. Covers attribute errors from a malformed credential
        # and TypeError from json.dumps — all become a clean refusal, never a
        # traceback. This is the only intentional broad except in this feature.
        # (Exception does not catch KeyboardInterrupt/SystemExit, which is correct.)
        logger.debug("generic credential-helper failed: %s", exc, exc_info=True)
        return (1, None, _REFUSAL_MESSAGE)
