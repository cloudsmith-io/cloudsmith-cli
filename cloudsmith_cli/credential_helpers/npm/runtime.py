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


def get_credentials(server_url, credential=None, api_host=None, org=None):
    """
    Get credentials for a Cloudsmith NPM registry.

    Verifies the URL is a Cloudsmith registry (including custom domains)
    and returns credentials if available.

    Args:
        server_url: The NPM registry server URL
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Organisation slug whose custom domains to match against

    Returns:
        dict: Credentials with 'Username' and 'Secret' keys, or None
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

    return credential.api_key


def execute(
    repo, credential=None, api_host=None, org=None
) -> tuple[int, str | None, str | None]:
    return _get_execute(repo, credential=credential, api_host=api_host, org=org)


def _get_execute(
    server_url: str, credential=None, api_host=None, org=None
) -> tuple[int, str | None, str | None]:
    try:
        cred = get_credentials(
            server_url, credential=credential, api_host=api_host, org=org
        )
        if not cred:
            return (1, None, _REFUSAL_MESSAGE)

        return (0, cred, None)
    except Exception as exc:
        logger.debug("npm credential-helper get failed: %s", exc, exc_info=True)

    return 1, None, None
