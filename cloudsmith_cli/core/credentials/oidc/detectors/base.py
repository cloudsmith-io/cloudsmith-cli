"""Base class and utilities for CI/CD environment OIDC detectors."""

from __future__ import annotations

import os

DEFAULT_OIDC_AUDIENCE = "cloudsmith"
OIDC_AUDIENCE_ENV_VAR = "CLOUDSMITH_OIDC_AUDIENCE"


def get_oidc_audience() -> str:
    """Return the OIDC audience to request, allowing override via env var."""
    return os.environ.get(OIDC_AUDIENCE_ENV_VAR, "").strip() or DEFAULT_OIDC_AUDIENCE


class EnvironmentDetector:
    """Base class for CI/CD environment detectors."""

    name: str = "base"

    def detect(self) -> bool:
        """Return True if running in this CI/CD environment."""
        raise NotImplementedError

    def get_token(self) -> str:
        """Retrieve the OIDC JWT from this environment. Raises on failure."""
        raise NotImplementedError
