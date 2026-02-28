"""Base class and utilities for CI/CD environment OIDC detectors."""

from __future__ import annotations

import os

import requests

DEFAULT_OIDC_AUDIENCE = "cloudsmith"
OIDC_AUDIENCE_ENV_VAR = "CLOUDSMITH_OIDC_AUDIENCE"


def get_oidc_audience() -> str:
    """Return the OIDC audience to request, allowing override via env var."""
    return os.environ.get(OIDC_AUDIENCE_ENV_VAR, "").strip() or DEFAULT_OIDC_AUDIENCE


class EnvironmentDetector:
    """Base class for CI/CD environment detectors."""

    name: str = "base"

    def __init__(
        self,
        proxy: str | None = None,
        ssl_verify: bool = True,
        user_agent: str | None = None,
        headers: dict | None = None,
    ):
        """Initialize detector with optional networking configuration.

        Args:
            proxy: HTTP/HTTPS proxy URL (optional).
            ssl_verify: Whether to verify SSL certificates (default: True).
            user_agent: Custom user-agent string (optional).
            headers: Additional headers to include (optional).
        """
        self.proxy = proxy
        self.ssl_verify = ssl_verify
        self.user_agent = user_agent
        self.headers = headers

    def detect(self) -> bool:
        """Return True if running in this CI/CD environment."""
        raise NotImplementedError

    def get_token(self) -> str:
        """Retrieve the OIDC JWT from this environment. Raises on failure."""
        raise NotImplementedError

    def _create_session(self) -> requests.Session:
        """Create a requests session configured with networking settings.

        Returns:
            Configured requests.Session instance.
        """
        session = requests.Session()

        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}

        session.verify = self.ssl_verify

        if self.user_agent:
            session.headers.update({"User-Agent": self.user_agent})

        if self.headers:
            session.headers.update(self.headers)

        return session
