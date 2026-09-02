"""Tests for the keyring credential provider."""

import os
from unittest.mock import MagicMock, patch

from cloudsmith_cli.core import keyring
from cloudsmith_cli.core.credentials.chain import CredentialProviderChain
from cloudsmith_cli.core.credentials.models import CredentialContext, CredentialResult
from cloudsmith_cli.core.credentials.providers import KeyringProvider, keyring_provider
from cloudsmith_cli.core.credentials.provider import CredentialProvider
from cloudsmith_cli.core.sso import SsoRenewalResult, SsoRenewalStatus


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

    def test_returns_none_on_refresh_failure(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock())
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="old_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(
                keyring_provider,
                "renew_sso_session",
                return_value=SsoRenewalResult(status=SsoRenewalStatus.FAILED),
            ),
        ):
            result = provider.resolve(context)
            assert result is None
            assert context.keyring_refresh_failed is True

    def test_passes_profile_to_keyring(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(
                keyring, "get_access_token", return_value="old_token"
            ) as get_access_mock,
            patch.object(
                keyring, "should_refresh_access_token", return_value=True
            ) as should_refresh_mock,
            patch.object(
                keyring_provider,
                "renew_sso_session",
                return_value=SsoRenewalResult(
                    status=SsoRenewalStatus.RENEWED,
                    access_token="new_token",
                ),
            ) as renew_mock,
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "new_token"
        get_access_mock.assert_called_once_with(context.api_host, profile="staging")
        should_refresh_mock.assert_called_once_with(
            context.api_host, access_token="old_token", profile="staging"
        )
        renew_mock.assert_called_once_with(
            context.api_host, context.session, profile="staging"
        )

    def test_rejected_session_continues_down_provider_chain(self):
        class FallbackProvider(CredentialProvider):
            name = "fallback"

            def resolve(self, context):
                return CredentialResult(
                    api_key="fallback-credential",
                    source_name=self.name,
                )

        context = CredentialContext(session=MagicMock())
        renewal = SsoRenewalResult(status=SsoRenewalStatus.REJECTED)
        with (
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="dead-token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring_provider, "renew_sso_session", return_value=renewal),
        ):
            result = CredentialProviderChain(
                [KeyringProvider(), FallbackProvider()]
            ).resolve(context)

        assert result.api_key == "fallback-credential"
        assert context.keyring_refresh_rejected is True

    def test_skips_refresh_when_no_refresh_token_is_stored(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="sso_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(
                keyring_provider,
                "renew_sso_session",
                return_value=SsoRenewalResult(
                    status=SsoRenewalStatus.UNRENEWABLE,
                    access_token="sso_token",
                ),
            ),
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "sso_token"
        assert context.keyring_refresh_unrenewable is True

    def test_keeps_tokens_on_transient_refresh_error(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="stale_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(
                keyring_provider,
                "renew_sso_session",
                return_value=SsoRenewalResult(
                    status=SsoRenewalStatus.CURRENT,
                    access_token="stale_token",
                    error=ConnectionError("offline"),
                ),
            ),
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "stale_token"
        assert context.keyring_refresh_failed is True

    def test_refresh_without_access_token_in_response_is_a_failure(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="stale_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(
                keyring_provider,
                "renew_sso_session",
                return_value=SsoRenewalResult(status=SsoRenewalStatus.FAILED),
            ),
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
