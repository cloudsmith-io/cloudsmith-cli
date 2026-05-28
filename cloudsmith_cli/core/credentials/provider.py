"""Base credential provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CredentialContext, CredentialResult


class CredentialProvider(ABC):
    """Base class for credential providers."""

    name: str = "base"

    @abstractmethod
    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        """Attempt to resolve credentials. Return CredentialResult or None."""
