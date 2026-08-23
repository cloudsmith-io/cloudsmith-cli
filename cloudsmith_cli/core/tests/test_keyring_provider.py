"""Tests for the keyring credential provider."""

import os
from unittest.mock import MagicMock, call, patch

import pytest

from cloudsmith_cli.cli import saml
from cloudsmith_cli.core import keyring
from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.providers import KeyringProvider, keyring_provider


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
            patch.object(keyring, "get_refresh_token", return_value="refresh_tok"),
            patch.object(
                saml,
                "refresh_access_token",
                side_effect=ApiException(status=401, detail="Unauthorized"),
            ),
            patch.object(keyring, "update_refresh_attempted_at"),
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
                keyring, "get_refresh_token", return_value="old_refresh"
            ) as get_refresh_mock,
            patch.object(
                keyring_provider,
                "refresh_access_token",
                return_value=("new_token", "new_refresh"),
            ),
            patch.object(keyring, "store_sso_tokens") as store_mock,
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "new_token"
        get_access_mock.assert_called_once_with(context.api_host, profile="staging")
        should_refresh_mock.assert_called_once_with(context.api_host, profile="staging")
        get_refresh_mock.assert_called_once_with(context.api_host, profile="staging")
        store_mock.assert_called_once_with(
            context.api_host, "new_token", "new_refresh", profile="staging"
        )

    @pytest.mark.parametrize("status", [400, 401, 403, 422])
    def test_wipes_tokens_when_refresh_is_rejected(self, status):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="stale_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring, "get_refresh_token", return_value="stale_refresh"),
            patch.object(
                keyring_provider,
                "refresh_access_token",
                side_effect=ApiException(status=status, detail="Rejected"),
            ),
            patch.object(keyring, "delete_sso_tokens") as delete_mock,
            patch.object(keyring, "update_refresh_attempted_at") as attempted_mock,
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        delete_mock.assert_called_once_with(
            context.api_host, profile="staging", include_legacy=False
        )
        attempted_mock.assert_not_called()

    def test_wipes_legacy_tokens_when_profile_has_none(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="stale_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring, "get_refresh_token", return_value="stale_refresh"),
            patch.object(
                keyring_provider,
                "refresh_access_token",
                side_effect=ApiException(status=401, detail="Rejected"),
            ),
            patch.object(
                keyring, "delete_sso_tokens", side_effect=[False, True]
            ) as delete_mock,
            patch.object(keyring, "update_refresh_attempted_at") as attempted_mock,
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        assert delete_mock.call_args_list == [
            call(context.api_host, profile="staging", include_legacy=False),
            call(context.api_host),
        ]
        attempted_mock.assert_not_called()

    def test_stamps_attempt_when_wipe_removes_nothing(self):
        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock(), profile="staging")
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(keyring, "should_use_keyring", return_value=True),
            patch.object(keyring, "get_access_token", return_value="stale_token"),
            patch.object(keyring, "should_refresh_access_token", return_value=True),
            patch.object(keyring, "get_refresh_token", return_value="stale_refresh"),
            patch.object(
                keyring_provider,
                "refresh_access_token",
                side_effect=ApiException(status=401, detail="Rejected"),
            ),
            patch.object(keyring, "delete_sso_tokens", return_value=False),
            patch.object(keyring, "update_refresh_attempted_at") as attempted_mock,
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        attempted_mock.assert_called_once_with(context.api_host, profile="staging")

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
            patch.object(keyring, "get_refresh_token", return_value=None),
            patch.object(keyring_provider, "refresh_access_token") as refresh_mock,
            patch.object(keyring, "delete_sso_tokens") as delete_mock,
        ):
            result = provider.resolve(context)

        assert result is not None
        assert result.api_key == "sso_token"
        assert context.keyring_refresh_failed is False
        refresh_mock.assert_not_called()
        delete_mock.assert_not_called()

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
            patch.object(keyring, "get_refresh_token", return_value="stale_refresh"),
            patch.object(
                keyring_provider,
                "refresh_access_token",
                side_effect=ApiException(status=503, detail="Service Unavailable"),
            ),
            patch.object(keyring, "delete_sso_tokens") as delete_mock,
            patch.object(keyring, "update_refresh_attempted_at") as attempted_mock,
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        delete_mock.assert_not_called()
        attempted_mock.assert_called_once_with(context.api_host, profile="staging")

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
            patch.object(keyring, "get_refresh_token", return_value="stale_refresh"),
            patch.object(
                keyring_provider,
                "refresh_access_token",
                return_value=(None, None),
            ),
            patch.object(keyring, "store_sso_tokens") as store_mock,
            patch.object(keyring, "update_refresh_attempted_at") as attempted_mock,
        ):
            result = provider.resolve(context)

        assert result is None
        assert context.keyring_refresh_failed is True
        store_mock.assert_not_called()
        attempted_mock.assert_called_once_with(context.api_host, profile="staging")
