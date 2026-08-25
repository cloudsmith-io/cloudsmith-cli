# Copyright 2026 Cloudsmith Ltd
"""
Cargo credential provider runtime.

Transport-light protocol logic for the Cargo credential provider protocol.
This module is intentionally free of Click/sys imports so it can be unit-tested
without invoking the CLI machinery.

Cargo speaks a line-delimited JSON *conversation* on stdin/stdout: the provider
announces the protocol versions it supports, then answers one request per line
until Cargo closes stdin.  Every outcome is reported in-band as an
``{"Ok": ...}`` / ``{"Err": ...}`` message; a non-zero exit code is not how a
provider reports "no credential".

See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html
"""

import json
import logging

from ..backends import BackendKind
from ..common import is_cloudsmith_domain

logger = logging.getLogger(__name__)

#: Protocol versions this provider implements, announced in the hello message.
SUPPORTED_VERSIONS = (1,)

_REFUSAL_MESSAGE = (
    "Error: Unable to retrieve credentials. "
    "Provide credentials via the CLOUDSMITH_API_KEY environment variable, "
    "credentials.ini, the system keyring, or an OIDC service. "
    "Verify current authentication with `cloudsmith whoami --verbose`."
)


def hello() -> dict:
    """Return the handshake message sent before any request is read.

    Cargo waits for this line to learn which protocol versions the provider
    speaks, and sets the ``v`` field of its requests to one of them.
    """
    return {"v": list(SUPPORTED_VERSIONS)}


def _ok(payload: dict) -> dict:
    """Wrap a success payload in the protocol's ``Ok`` envelope."""
    return {"Ok": payload}


def _err(kind: str, message: str | None = None) -> dict:
    """Wrap an error *kind* in the protocol's ``Err`` envelope.

    ``url-not-supported`` tells Cargo to move on to the next configured
    provider, so it is the correct answer for a non-Cloudsmith registry —
    installing this helper globally must not break authentication to
    crates.io or to a third-party registry.
    """
    error: dict = {"kind": kind}
    if message is not None:
        error["message"] = message
    return {"Err": error}


def is_supported_registry(index_url, credential=None, api_host=None, org=None) -> bool:
    """Return True when *index_url* is a Cloudsmith Cargo registry.

    Args:
        index_url: The registry index URL from the request (may carry Cargo's
            ``sparse+`` prefix, which :func:`extract_hostname` strips)
        credential: Pre-resolved CredentialResult, used to authenticate the
            custom-domain lookup
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against
    """
    if not index_url:
        return False

    return is_cloudsmith_domain(
        index_url,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.CARGO,
        org=org,
    )


def get_credentials(index_url, credential=None, api_host=None, org=None):
    """
    Get the token for a Cloudsmith Cargo registry.

    Verifies the index URL is a Cloudsmith registry (including custom domains)
    and returns the token if one is available.

    Args:
        index_url: The Cargo registry index URL
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        str: The complete value Cargo sends as its ``Authorization`` header,
            or None
    """
    if not credential or not credential.api_key:
        return None

    if not is_supported_registry(
        index_url, credential=credential, api_host=api_host, org=org
    ):
        return None

    return _authorization_value(credential)


def _authorization_value(credential) -> str:
    """Return the complete HTTP Authorization value for *credential*.

    Cargo forwards the credential provider's ``token`` field verbatim as the
    Authorization header. Cloudsmith API credentials use the ``token`` scheme,
    while SSO credentials use ``Bearer``.
    """
    scheme = "Bearer" if credential.auth_type == "bearer" else "token"
    return f"{scheme} {credential.api_key}"


def _handle_get(request, credential, api_host, org) -> dict:
    """Answer a ``get`` request with a token, or with why there isn't one."""
    registry = request.get("registry")
    if not isinstance(registry, dict):
        return _err("other", "Request is missing registry information")

    index_url = registry.get("index-url")
    if not index_url:
        return _err("other", "Request is missing the registry index-url")

    # Order matters: a registry we don't serve must fall through to the next
    # provider (url-not-supported) whether or not we hold a credential, and a
    # Cloudsmith registry we can't authenticate is not-found rather than
    # unsupported.
    if not is_supported_registry(
        index_url, credential=credential, api_host=api_host, org=org
    ):
        return _err("url-not-supported")

    if not credential or not credential.api_key:
        return _err("not-found")

    return _ok(
        {
            "kind": "get",
            "token": _authorization_value(credential),
            # A Cloudsmith token is organisation-wide and not scoped to the
            # read/publish/yank/owners operation, so it is cacheable for the
            # session and across operations.
            "cache": "session",
            "operation_independent": True,
        }
    )


def handle_request(request, credential=None, api_host=None, org=None) -> dict:
    """
    Answer a single decoded Cargo credential-provider request.

    Args:
        request: The decoded request object (one JSON line from Cargo)
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        dict: The response message to serialise back to Cargo.
    """
    if not isinstance(request, dict):
        return _err("other", "Request is not a JSON object")

    version = request.get("v")
    if version not in SUPPORTED_VERSIONS:
        return _err(
            "other",
            f"Unsupported protocol version {version!r}"
            f" (supported: {', '.join(str(v) for v in SUPPORTED_VERSIONS)})",
        )

    kind = request.get("kind")
    if kind == "get":
        return _handle_get(request, credential, api_host, org)

    if kind in ("login", "logout"):
        # Credentials are resolved from the Cloudsmith CLI's own provider chain
        # (API key, credentials.ini, keyring, OIDC), so there is nothing for
        # `cargo login`/`cargo logout` to store or clear here.
        return _err("operation-not-supported")

    return _err("operation-not-supported")


def _write_message(stdout, message) -> None:
    """Write one newline-delimited JSON message and flush it.

    Cargo reads line by line and blocks on the next message, so an unflushed
    buffer deadlocks the exchange.
    """
    stdout.write(json.dumps(message) + "\n")
    stdout.flush()


def execute(stdin, stdout, credential=None, api_host=None, org=None):
    """
    Run a Cargo credential-provider session.

    Emits the hello message, then answers one request per line of *stdin*
    until Cargo closes it.

    Args:
        stdin: A file-like object to read newline-delimited requests from
        stdout: A file-like object to write newline-delimited responses to
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        A (exit_code, stderr_text) tuple.  Protocol-level outcomes are reported
        in-band to Cargo, so the exit code only distinguishes a clean session
        from one that could not answer for lack of credentials (or that broke
        at the transport level); *stderr_text* is None when there is nothing to
        tell the user.
    """
    refused = False

    try:
        _write_message(stdout, hello())

        for line in stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except (json.JSONDecodeError, ValueError) as exc:
                response = _err("other", f"Malformed request: {exc}")
            else:
                response = handle_request(
                    request, credential=credential, api_host=api_host, org=org
                )

            if response.get("Err", {}).get("kind") == "not-found":
                refused = True

            _write_message(stdout, response)
    except Exception as exc:  # pylint: disable=broad-except
        # Protocol boundary: a credential provider must never crash `cargo
        # build`/`publish` with a traceback.  Covers broken-pipe OSError from
        # stdin/stdout, network/SDK errors from the custom-domain lookup, and
        # TypeError from json.dumps — all degrade to a clean exit.
        # (Exception does not catch KeyboardInterrupt/SystemExit, which is correct.)
        logger.debug("cargo credential-provider session failed: %s", exc, exc_info=True)
        return (1, _REFUSAL_MESSAGE)

    if refused:
        return (1, _REFUSAL_MESSAGE)

    return (0, None)
