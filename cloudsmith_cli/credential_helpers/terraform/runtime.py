# Copyright 2026 Cloudsmith Ltd
"""
Terraform credentials helper runtime.

Transport-light protocol logic for Terraform's credentials-helper protocol.
This module is intentionally free of Click/sys imports so it can be unit-tested
without invoking the CLI machinery.

Terraform runs a credentials helper once per credentials request it cannot
satisfy from a ``credentials`` block in the CLI configuration, invoking it as::

    terraform-credentials-cloudsmith [args...] <verb> <hostname>

The current verbs are ``get``, ``store`` and ``forget``.  This helper only
serves ``get``:

* ``get`` for a Cloudsmith host with an available credential prints a JSON
  credentials object (``{"token": "..."}``) to stdout and exits zero.
* ``get`` for a host we definitively have no credentials for (a non-Cloudsmith
  host) prints an empty JSON object (``{}``) to stdout and exits zero, so
  Terraform falls back to its own credential sources.
* ``get`` for a Cloudsmith host we cannot authenticate prints an
  end-user-oriented error to stderr and exits non-zero.
* ``store``/``forget`` and any unknown verb print an error to stderr and exit
  non-zero — credentials come from the Cloudsmith CLI's own provider chain, so
  there is nothing to store or forget.

See: https://developer.hashicorp.com/terraform/internals/credentials-helpers
"""

import json
import logging

from ..backends import BackendKind
from ..common import is_cloudsmith_domain

logger = logging.getLogger(__name__)

_REFUSAL_MESSAGE = (
    "Error: Unable to retrieve credentials. "
    "Provide credentials via the CLOUDSMITH_API_KEY environment variable, "
    "credentials.ini, the system keyring, or an OIDC service. "
    "Verify current authentication with `cloudsmith whoami --verbose`."
)


def get_token(hostname, credential=None, api_host=None, org=None):
    """
    Get the token for a Cloudsmith Terraform registry.

    Verifies the hostname is a Cloudsmith registry (including custom domains)
    and returns the token if one is available.

    Args:
        hostname: The Terraform registry hostname
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        str: The token Terraform sends as its bearer credential, or None when
        this is not a Cloudsmith host or no credential is available.
    """
    if not is_cloudsmith_domain(
        hostname,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.TERRAFORM,
        org=org,
    ):
        return None

    if not credential or not credential.api_key:
        return None

    return credential.api_key


def _execute_get(
    hostname, credential, api_host, org
) -> tuple[int, str | None, str | None]:
    """Handle the 'get' verb of the Terraform credentials-helper protocol.

    Distinguishes two "no token" outcomes, per the protocol:

    * A host that is not a Cloudsmith one is *not ours to answer* — emit an
      empty ``{}`` and exit zero so Terraform falls through to its own
      credential sources rather than failing the request.
    * A Cloudsmith host we hold no credential for is a *definitive failure* —
      emit an actionable error on stderr and exit non-zero.
    """
    if not hostname:
        return (1, None, "Error: No hostname provided")

    if not is_cloudsmith_domain(
        hostname,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.TERRAFORM,
        org=org,
    ):
        # Not a Cloudsmith host: emit an empty object so Terraform moves on to
        # its own credential sources instead of treating this as an error.
        return (0, "{}", None)

    token = get_token(hostname, credential=credential, api_host=api_host, org=org)
    if not token:
        return (1, None, _REFUSAL_MESSAGE)

    return (0, json.dumps({"token": token}), None)


def execute(
    verb, hostname, credential=None, api_host=None, org=None
) -> tuple[int, str | None, str | None]:
    """
    Execute a Terraform credentials-helper protocol verb.

    Args:
        verb: One of 'get', 'store', 'forget'
        hostname: The registry hostname the verb applies to (used by 'get')
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        A (exit_code, stdout_text, stderr_text) tuple.  Either text value may
        be None if there is nothing to write to that stream.
    """
    if verb == "get":
        try:
            return _execute_get(hostname, credential, api_host, org)
        except Exception as exc:  # pylint: disable=broad-except
            # Protocol boundary: a credentials helper must never crash
            # `terraform init` with a traceback.  Covers network/SDK errors
            # from the custom-domain lookup and TypeError from json.dumps — all
            # degrade to a clean refusal (exit 1), not a traceback.
            # (Exception does not catch KeyboardInterrupt/SystemExit, which is
            # correct.)
            logger.debug(
                "terraform credentials-helper get failed: %s", exc, exc_info=True
            )
            return (1, None, _REFUSAL_MESSAGE)

    if verb in ("store", "forget"):
        # Credentials are resolved from the Cloudsmith CLI's own provider chain
        # (API key, credentials.ini, keyring, OIDC), so there is nothing for
        # Terraform to store or forget here.
        return (
            1,
            None,
            (
                f"Error: '{verb}' is not supported. Credentials are managed by "
                "the Cloudsmith credential chain and cannot be stored or "
                "forgotten by this helper."
            ),
        )

    # Forward-compatibility: react to any unsupported verb with an error and a
    # non-zero exit, as the protocol requires.
    return (
        1,
        None,
        f"Error: Unknown verb '{verb}'. Valid verbs: get, store, forget",
    )
