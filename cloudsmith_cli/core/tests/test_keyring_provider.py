"""Tests for the keyring credential provider."""

import os
from unittest.mock import MagicMock, patch

from cloudsmith_cli.core import keyring
from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers import KeyringProvider, keyring_provider
from cloudsmith_cli.core.sso import SsoRenewalResult, SsoRenewalStatus


class TestKeyringProvider:
    def test_returns_none_when_keyring_disabled(self):
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            assert KeyringProvider().resolve(CredentialContext()) is None

    def test_returns_none_when_no_token(self):
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value=None),
        ):
            assert KeyringProvider().resolve(CredentialContext()) is None

    def test_returns_bearer_token_without_refresh(self):
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="sso-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=False),
        ):
            result = KeyringProvider().resolve(CredentialContext())

        assert result is not None
        assert (result.api_key, result.auth_type) == ("sso-token", "bearer")

    def test_transient_failure_retains_usable_token(self):
        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(
            status=SsoRenewalStatus.CURRENT,
            access_token="still-usable",
            error=ConnectionError("offline"),
        )
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="old-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = KeyringProvider().resolve(context)

        assert result is not None
        assert result.api_key == "still-usable"
        assert context.keyring_refresh_failed is True

    def test_rejected_session_is_not_returned(self):
        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(status=SsoRenewalStatus.REJECTED)
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="dead-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = KeyringProvider().resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        assert context.keyring_refresh_rejected is True
