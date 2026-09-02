"""Tests for the keyring credential provider."""

import os
from unittest.mock import MagicMock, patch

import pytest

from cloudsmith_cli.core import keyring
from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers import KeyringProvider, keyring_provider
from cloudsmith_cli.core.sso import SsoRenewalResult


@pytest.fixture(autouse=True)
def mock_get_keyring():
    import keyring as keyring_backend

    with patch.object(keyring_backend, "get_keyring") as get_keyring_mock:
        yield get_keyring_mock


class TestKeyringProvider:
    def test_returns_none_when_keyring_disabled(self):
        provider = KeyringProvider()
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            result = provider.resolve(CredentialContext())
            assert result is None

    def test_returns_none_when_no_token(self):
        provider = KeyringProvider()
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value=None),
        ):
            result = provider.resolve(CredentialContext())
            assert result is None

    def test_returns_bearer_token(self):
        provider = KeyringProvider()
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="sso_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=False),
        ):
            result = provider.resolve(CredentialContext())
            assert result is not None
            assert result.api_key == "sso_token"
            assert result.auth_type == "bearer"
            assert result.source_name == "keyring"

    def test_uses_existing_token_when_session_is_unavailable(self):
        provider = KeyringProvider()
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="sso-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session") as renew_mock,
        ):
            result = provider.resolve(CredentialContext())

        assert result is not None
        assert result.api_key == "sso-token"
        renew_mock.assert_not_called()

    def test_uses_renewed_token_and_profile(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        renewal = SsoRenewalResult(status="renewed", access_token="new-token")
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(
                keyring, "get_access_token", return_value="old-token"
            ) as get_access_mock,
            patch.object(
                keyring, "should_refresh_access_token", return_value=True
            ) as should_refresh_mock,
            patch.object(
                keyring_provider, "renew_sso_session", return_value=renewal
            ) as renew_mock,
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "new-token"
        get_access_mock.assert_called_once_with(context.api_host, profile="staging")
        should_refresh_mock.assert_called_once_with(
            context.api_host, access_token="old-token", profile="staging"
        )
        renew_mock.assert_called_once_with(
            context.api_host, context.session, profile="staging"
        )

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("temporarily unavailable"),
            ValueError("Cloudsmith did not return a new SSO access token."),
        ],
        ids=["transient-error", "missing-access-response"],
    )
    def test_renewal_failure_uses_still_valid_token(self, error):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(
            status="current",
            access_token="old-token",
            error=error,
        )
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="old-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "old-token"
        assert context.keyring_refresh_failed is True

    def test_unrenewable_session_uses_still_valid_token(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(
            status="unrenewable",
            access_token="old-token",
        )
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="old-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "old-token"
        assert context.keyring_refresh_failed is True
        assert context.keyring_refresh_unrenewable is True

    def test_rejected_dead_session_returns_no_credential(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(status="rejected")
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="old-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        assert context.keyring_refresh_rejected is True
