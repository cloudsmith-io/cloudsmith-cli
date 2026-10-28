"""Tests for the OIDC credential provider."""

import json
import logging
from unittest.mock import Mock, patch

import jwt
import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext, CredentialResult
from cloudsmith_cli.core.credentials.oidc.cache import _cache_key
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


def _resolve_with_disk_cache(config_dir: str) -> CredentialResult | None:
    detector = Mock()
    detector.name = "github-actions"
    detector.get_token.return_value = "vendor-token"

    with (
        patch("cloudsmith_cli.core.keyring.should_use_keyring", return_value=False),
        patch(
            "cloudsmith_cli.cli.config.get_default_config_path",
            return_value=config_dir,
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
        return OidcProvider().resolve(_context())


def test_uncreatable_cache_dir_does_not_block_exchange(tmp_path):
    with patch("os.makedirs", side_effect=PermissionError("read-only home")):
        credential = _resolve_with_disk_cache(str(tmp_path / "missing"))

    assert credential is not None
    assert credential.api_key == "exchanged-token"


@pytest.mark.parametrize(
    "entry",
    [[], {"token": 123}, {"token": "cached-token", "expires_at": "soon"}],
    ids=["not-an-object", "non-string-token", "non-numeric-expiry"],
)
def test_malformed_disk_cache_entry_does_not_block_exchange(tmp_path, entry):
    context = _context()
    cache_dir = tmp_path / "oidc_token_cache"
    cache_dir.mkdir()
    cache_key = _cache_key(context.api_host, context.org, context.oidc_service_slug)
    (cache_dir / cache_key).write_text(json.dumps(entry))

    credential = _resolve_with_disk_cache(str(tmp_path))

    assert credential is not None
    assert credential.api_key == "exchanged-token"
