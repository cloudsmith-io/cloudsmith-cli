"""
Pip keyring backend for Cloudsmith.

This module provides a keyring backend that pip can use to automatically
authenticate with Cloudsmith Python repositories.

The backend is auto-discovered by the keyring library and used by pip when
installing packages from Cloudsmith feeds. No configuration is needed beyond
installing cloudsmith-cli:

    pip install mypackage --index-url https://python.cloudsmith.io/org/repo/simple/

See: https://pip.pypa.io/en/stable/topics/authentication/#keyring-support
"""

import logging

import keyring.backend
import keyring.credentials

from ..common import is_cloudsmith_domain, resolve_credentials

logger = logging.getLogger(__name__)


class CloudsmithKeyringBackend(keyring.backend.KeyringBackend):
    """
    Keyring backend for Cloudsmith Python repositories.

    This backend integrates with pip and twine to provide automatic authentication
    for Cloudsmith Python feeds using the Cloudsmith credential provider chain.

    Supported URLs:
        - Standard domains: *.cloudsmith.io
        - Custom domains: Fetched from API

    Priority:
        9.9 (high priority - runs before system keychains)

    Usage:
        Once installed, pip automatically uses this backend:

        $ pip install mypackage --index-url https://python.cloudsmith.io/myorg/myrepo/simple/

    Requirements:
        - Either CLOUDSMITH_API_KEY environment variable
        - Or CLOUDSMITH_ORG + CLOUDSMITH_SERVICE_SLUG for OIDC authentication
        - Or credentials in ~/.cloudsmith/config.ini
    """

    priority = 9.9
    _resolving = False

    def __init__(self):
        """Initialize the backend with an in-memory cache."""
        super().__init__()
        self._cache = {}

    def get_credential(self, service, username):
        """
        Get credentials for a Cloudsmith service URL.

        Args:
            service: URL of the Python repository
            username: Username (ignored - we always use 'token')

        Returns:
            keyring.credentials.SimpleCredential or None
        """
        try:
            # Reentrancy guard: the KeyringProvider in the credential chain
            # calls keyring.get_password() which invokes this backend. Without
            # this guard that would loop forever.
            if CloudsmithKeyringBackend._resolving:
                return None
            CloudsmithKeyringBackend._resolving = True

            try:
                result = resolve_credentials()
                if not result:
                    logger.debug("No credentials resolved from provider chain")
                    return None

                if not is_cloudsmith_domain(service, _credential_result=result):
                    logger.debug("Not a Cloudsmith domain: %s", service)
                    return None

                logger.debug(
                    "Credentials resolved for %s via %s", service, result.source_name
                )
                username = "token"
                self._cache[(service, username)] = result.api_key
                return keyring.credentials.SimpleCredential(username, result.api_key)
            finally:
                CloudsmithKeyringBackend._resolving = False

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Error getting credentials: %s", exc, exc_info=True)
            return None

    def get_password(self, service, username):
        """
        Get password for a service and username.

        Args:
            service: URL of the Python repository
            username: Username to get password for

        Returns:
            str: Password/API key or None
        """
        password = self._cache.pop((service, username), None)
        if password is not None:
            return password

        creds = self.get_credential(service, None)
        if creds and username == creds.username:
            return creds.password

        return None

    def set_password(self, service, username, password):
        """Not supported - credentials are dynamic."""
        raise NotImplementedError(
            "CloudsmithKeyringBackend does not support storing passwords. "
            "Use CLOUDSMITH_API_KEY environment variable or config file instead."
        )

    def delete_password(self, service, username):
        """Not supported - credentials are dynamic."""
        raise NotImplementedError(
            "CloudsmithKeyringBackend does not support deleting passwords. "
            "Credentials are managed via environment variables or config files."
        )
