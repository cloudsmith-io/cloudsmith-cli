"""Credential Provider Chain for Cloudsmith CLI.

Implements an AWS SDK-style credential resolution chain that evaluates
credential sources sequentially and returns the first valid result.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)


@dataclass
class CredentialContext:
    """Context passed to credential providers during resolution.

    All values are populated directly from Click options / ``opts``.
    """

    session: requests.Session | None = None
    api_key: str | None = None
    api_host: str = "https://api.cloudsmith.io"
    creds_file_path: str | None = None
    profile: str | None = None
    debug: bool = False
    keyring_refresh_failed: bool = False


@dataclass
class CredentialResult:
    """Result from a successful credential resolution."""

    api_key: str
    source_name: str
    source_detail: str | None = None
    auth_type: str = "api_key"


class CredentialProvider(ABC):
    """Base class for credential providers."""

    name: str = "base"

    @abstractmethod
    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        """Attempt to resolve credentials. Return CredentialResult or None."""


class CredentialProviderChain:
    """Evaluates credential providers in order, returning the first valid result.

    If no providers are given, uses the default chain:
    Keyring → CLIFlag.
    """

    def __init__(self, providers: list[CredentialProvider] | None = None):
        if providers is not None:
            self.providers = providers
        else:
            from .providers import CLIFlagProvider, KeyringProvider

            self.providers = [
                KeyringProvider(),
                CLIFlagProvider(),
            ]

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        """Evaluate each provider in order. Return the first successful result."""
        for provider in self.providers:
            try:
                result = provider.resolve(context)
                if result is not None:
                    if context.debug:
                        logger.debug(
                            "Credentials resolved by %s: %s",
                            provider.name,
                            result.source_detail or result.source_name,
                        )
                    return result
                if context.debug:
                    logger.debug(
                        "Provider %s did not resolve credentials, trying next",
                        provider.name,
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                # Intentionally broad - one provider failing shouldn't stop others
                logger.debug(
                    "Provider %s raised an exception, skipping",
                    provider.name,
                    exc_info=True,
                )
                continue
        return None
