"""Base class and utilities for OIDC environment detectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ... import CredentialContext


class EnvironmentDetector:
    """Base class for OIDC environment detectors."""

    name: str = "base"

    def __init__(self, context: CredentialContext):
        self.context = context

    def detect(self) -> bool:
        """Return True if running in a supported OIDC environment."""
        raise NotImplementedError

    def get_token(self) -> str:
        """Retrieve the OIDC JWT from this environment. Raises on failure."""
        raise NotImplementedError
