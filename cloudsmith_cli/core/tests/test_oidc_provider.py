"""Tests for the OIDC credential provider."""

import logging
from unittest.mock import Mock, patch

import jwt

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc.cache import CachedToken
from cloudsmith_cli.core.credentials.oidc.exchange import OidcExchangeError
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
        return_value=CachedToken("cached-token"),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential is not None
    assert credential.auth_type == "bearer"


def test_cached_oidc_token_names_the_vendor():
    """The source of a cached token names the CI vendor whose token was exchanged."""
    with patch(
        "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
        return_value=CachedToken("cached-token", detector="GitHub Actions"),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential.api_key == "cached-token"
    assert credential.source_detail == (
        "OIDC via GitHub Actions [cached] (org: cloudsmith, service: github-actions)"
    )


def test_cached_oidc_token_without_a_vendor_keeps_the_old_source():
    """A token that an older CLI cached has no vendor name."""
    with patch(
        "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
        return_value=CachedToken("cached-token"),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential.source_detail == (
        "OIDC [cached] (org: cloudsmith, service: github-actions)"
    )


def test_exchanged_oidc_token_is_cached_with_the_vendor():
    """The cache keeps the vendor name, so a cached token can name it later."""
    detector = Mock()
    detector.name = "GitHub Actions"
    detector.get_token.return_value = "vendor-token"

    with (
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.store_cached_token",
        ) as store,
        patch(
            "cloudsmith_cli.core.credentials.oidc.detectors.detect_environment",
            return_value=detector,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token",
            return_value="exchanged-token",
        ),
    ):
        OidcProvider().resolve(_context())

    store.assert_called_once_with(
        "https://api.cloudsmith.io",
        "cloudsmith",
        "github-actions",
        "exchanged-token",
        detector="GitHub Actions",
    )


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


def test_failed_exchange_logs_vendor_jwt_diagnostics(caplog):
    vendor_token = jwt.encode(
        {
            "iss": "https://token.actions.githubusercontent.com",
            "aud": "cloudsmith",
            "repository": "cloudsmith-io/cloudsmith-cli",
        },
        key="",
        algorithm="none",
        headers={"kid": "vendor-key-id"},
    )
    detector = Mock()
    detector.name = "GitHub Actions"
    detector.get_token.return_value = vendor_token

    with (
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.detectors.detect_environment",
            return_value=detector,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token",
            side_effect=OidcExchangeError("service not found"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential is None
    assert "Workspace: cloudsmith" in caplog.text
    assert "Service slug: github-actions" in caplog.text
    assert "Cloudsmith API host: https://api.cloudsmith.io" in caplog.text
    assert "Vendor detector: GitHub Actions" in caplog.text
    assert (
        "Vendor issuer URL: https://token.actions.githubusercontent.com" in caplog.text
    )
    assert "Vendor JWT KID: vendor-key-id" in caplog.text
    assert '"repository": "cloudsmith-io/cloudsmith-cli"' in caplog.text
    assert vendor_token not in caplog.text


def test_failed_exchange_reports_undecodable_vendor_jwt(caplog):
    detector = Mock()
    detector.name = "Generic"
    detector.get_token.return_value = "not-a-jwt"

    with (
        patch(
            "cloudsmith_cli.core.credentials.oidc.cache.get_cached_token",
            return_value=None,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.detectors.detect_environment",
            return_value=detector,
        ),
        patch(
            "cloudsmith_cli.core.credentials.oidc.exchange.exchange_oidc_token",
            side_effect=OidcExchangeError("unauthorized"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        credential = OidcProvider().resolve(_context())

    assert credential is None
    assert "Vendor JWT could not be decoded" in caplog.text
    assert "not-a-jwt" not in caplog.text
