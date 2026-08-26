"""Tests for the OIDC credential provider."""

from unittest.mock import Mock, patch

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers.oidc_provider import OidcProvider


def _context() -> CredentialContext:
    return CredentialContext(
        org="cloudsmith",
        oidc_service_slug="github-actions",
    )


def test_cached_oidc_token_is_a_bearer_credential():
    """Cached exchanged tokens retain their HTTP authorization scheme."""
    with patch(
        "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
        return_value="cached-token",
    ):
        credential = OidcProvider().resolve(_context())

    assert credential is not None
    assert credential.auth_type == "bearer"


def test_exchanged_oidc_token_is_a_bearer_credential():
    """Freshly exchanged tokens use Bearer authentication."""
    detector = Mock(name="github-actions")
    detector.name = "github-actions"
    detector.get_token.return_value = "vendor-token"

    with (
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.store_cached_token",
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.detectors.detect_environment",
            return_value=detector,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token",
            return_value="exchanged-token",
        ),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential is not None
    assert credential.auth_type == "bearer"
