# Copyright 2026 Cloudsmith Ltd
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


def get_pnpm_credentials(server_url, credential=None, api_host=None, org=None):
    """
    Get credentials for a Cloudsmith pnpm registry.

    Verifies the URL is a Cloudsmith registry (including custom domains)
    and returns credentials if available.

    Args:
        server_url: The pnpm registry server URL
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        str: the token in plain text, with no newline at the end
    """
    if not credential or not credential.api_key:
        return None

    if not is_cloudsmith_domain(
        server_url,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.NPM,
        org=org,
    ):
        return None

    scheme = "Bearer" if credential.auth_type == "bearer" else "token"
    return f"{scheme} {credential.api_key}"


def execute(
    repo, credential=None, api_host=None, org=None
) -> tuple[int, str | None, str | None]:
    return _get_execute(repo, credential=credential, api_host=api_host, org=org)


def _get_execute(
    server_url: str, credential=None, api_host=None, org=None
) -> tuple[int, str | None, str | None]:
    try:
        cred = get_pnpm_credentials(
            server_url, credential=credential, api_host=api_host, org=org
        )
        if not cred:
            return (1, None, _REFUSAL_MESSAGE)

        return (0, cred, None)
    except Exception as exc:
        logger.debug("pnpm credential-helper get failed: %s", exc, exc_info=True)

    return 1, None, _REFUSAL_MESSAGE
