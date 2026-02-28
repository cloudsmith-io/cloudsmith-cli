"""Credential Provider Chain for Cloudsmith CLI.

Implements an AWS SDK-style credential resolution chain that evaluates
credential sources sequentially and returns the first valid result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CredentialContext:
    """Context passed to credential providers during resolution."""

    api_host: str = "https://api.cloudsmith.io"
    config_file_path: str | None = None
    creds_file_path: str | None = None
    profile: str | None = None
    debug: bool = False
    # Pre-resolved values from CLI flags (highest priority)
    cli_api_key: str | None = None
    # API networking configuration
    proxy: str | None = None
    ssl_verify: bool = True
    user_agent: str | None = None
    headers: dict | None = None


@dataclass
class CredentialResult:
    """Result from a successful credential resolution."""

    api_key: str
    source_name: str
    source_detail: str | None = None


class CredentialProvider:
    """Base class for credential providers."""

    name: str = "base"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        """Attempt to resolve credentials. Return CredentialResult or None."""
        raise NotImplementedError


class CredentialProviderChain:
    """Evaluates credential providers in order, returning the first valid result."""

    def __init__(self, providers: list[CredentialProvider]):
        self.providers = providers

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
