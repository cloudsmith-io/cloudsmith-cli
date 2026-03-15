"""Tests for the keyring credential provider."""

import os
from unittest.mock import MagicMock, patch

from cloudsmith_cli.core.credentials import CredentialContext
from cloudsmith_cli.core.credentials.providers import KeyringProvider


class TestKeyringProvider:
    def test_returns_none_when_keyring_disabled(self):
        provider = KeyringProvider()
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            result = provider.resolve(CredentialContext())
            assert result is None

    def test_returns_none_when_no_token(self):
        from cloudsmith_cli.core import keyring

        provider = KeyringProvider()
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            with patch.object(keyring, "should_use_keyring", return_value=True):
                with patch.object(keyring, "get_access_token", return_value=None):
                    result = provider.resolve(CredentialContext())
                    assert result is None

    def test_returns_bearer_token(self):
        from cloudsmith_cli.core import keyring

        provider = KeyringProvider()
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            with patch.object(keyring, "should_use_keyring", return_value=True):
                with patch.object(
                    keyring, "get_access_token", return_value="sso_token"
                ):
                    with patch.object(
                        keyring, "should_refresh_access_token", return_value=False
                    ):
                        result = provider.resolve(CredentialContext())
                        assert result is not None
                        assert result.api_key == "sso_token"
                        assert result.auth_type == "bearer"
                        assert result.source_name == "keyring"

    def test_returns_none_on_refresh_failure(self):
        from cloudsmith_cli.cli import saml
        from cloudsmith_cli.core import keyring
        from cloudsmith_cli.core.api.exceptions import ApiException

        provider = KeyringProvider()
        context = CredentialContext(session=MagicMock())
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            with patch.object(keyring, "should_use_keyring", return_value=True):
                with patch.object(
                    keyring, "get_access_token", return_value="old_token"
                ):
                    with patch.object(
                        keyring, "should_refresh_access_token", return_value=True
                    ):
                        with patch.object(
                            keyring, "get_refresh_token", return_value="refresh_tok"
                        ):
                            with patch.object(
                                saml,
                                "refresh_access_token",
                                side_effect=ApiException(
                                    status=401, detail="Unauthorized"
                                ),
                            ):
                                with patch.object(
                                    keyring, "update_refresh_attempted_at"
                                ):
                                    result = provider.resolve(context)
                                    assert result is None
                                    assert context.keyring_refresh_failed is True
