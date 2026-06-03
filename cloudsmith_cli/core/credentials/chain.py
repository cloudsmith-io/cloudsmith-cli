"""Credential provider chain for the Cloudsmith CLI.

Implements an AWS SDK-style credential resolution chain that evaluates
credential sources sequentially and returns the first valid result.
"""

from __future__ import annotations

import logging

from .models import CredentialContext, CredentialResult
from .provider import CredentialProvider
from .providers import (
    CLIFlagProvider,
    CredentialsFileProvider,
    EnvVarProvider,
    KeyringProvider,
    OidcProvider,
)

logger = logging.getLogger(__name__)


class CredentialProviderChain:
    """Evaluates credential providers in order, returning the first valid result.

    If no providers are given, uses the default chain:
    CLIFlag → EnvVar → CredentialsFile → Keyring → OIDC.
    """

    def __init__(self, providers: list[CredentialProvider] | None = None):
        if providers is not None:
            self.providers = providers
        else:
            self.providers = [
                CLIFlagProvider(),
                EnvVarProvider(),
                CredentialsFileProvider(),
                KeyringProvider(),
                OidcProvider(),
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
