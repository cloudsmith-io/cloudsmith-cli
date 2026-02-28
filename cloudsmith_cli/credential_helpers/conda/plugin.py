"""
Conda plugin for Cloudsmith authentication.

This module implements the conda auth handler plugin interface,
providing automatic authentication for Cloudsmith Conda channels.

See: https://docs.conda.io/projects/conda/en/stable/dev-guide/plugins/auth_handlers.html

Install and configure in .condarc:
    channel_settings:
      - channel: https://conda.cloudsmith.io/org/repo/
        auth: cloudsmith
"""

import logging

from . import get_credentials

logger = logging.getLogger(__name__)

try:
    from conda.plugins import hookimpl
    from conda.plugins.types import CondaAuthHandler
    from requests.auth import HTTPBasicAuth

    class CloudsmithCondaAuth(HTTPBasicAuth):
        """Requests auth handler that injects Cloudsmith credentials via HTTP Basic Auth."""

        def __init__(self, channel_name=None):
            """Initialize with placeholder credentials (resolved per-request)."""
            super().__init__("token", "")
            self.channel_name = channel_name

        def __call__(self, request):
            """Add authentication to the request."""
            creds = get_credentials(request.url)
            if creds:
                username, token = creds
                self.username = username
                self.password = token
                logger.debug("Injected Cloudsmith basic auth for %s", request.url)
                return super().__call__(request)
            return request

    @hookimpl
    def conda_auth_handlers():
        """Register the Cloudsmith auth handler with conda."""
        yield CondaAuthHandler(
            name="cloudsmith",
            handler=CloudsmithCondaAuth,
        )

except ImportError:
    # conda is not installed - plugin hooks won't be available
    # This is fine when running outside of conda environments
    logger.debug("conda not available, skipping plugin registration")
