import os
from unittest.mock import patch

import pytest

import cloudsmith_cli.core.api.init as init_module

from ...cli import saml
from .. import keyring
from ..api.init import CliConfig, initialise_api


@pytest.fixture
def mocked_get_access_token():
    with patch.object(
        keyring, "get_access_token", return_value="dummy_access_token"
    ) as get_access_token_mock:
        yield get_access_token_mock


@pytest.fixture
def mocked_get_refresh_token():
    with patch.object(
        keyring, "get_refresh_token", return_value="dummy_refresh_token"
    ) as get_refresh_token_mock:
        yield get_refresh_token_mock


@pytest.fixture
def mocked_should_refresh_access_token():
    with patch.object(
        keyring, "should_refresh_access_token", return_value=False
    ) as should_refresh_access_token_mock:
        yield should_refresh_access_token_mock


@pytest.fixture
def mocked_refresh_access_token():
    with patch.object(
        saml,
        "refresh_access_token",
        return_value=("new_access_token", "new_refresh_token"),
    ) as refresh_access_token_mock:
        yield refresh_access_token_mock


@pytest.fixture
def mocked_store_sso_tokens():
    with patch.object(keyring, "store_sso_tokens") as store_sso_tokens_mock:
        yield store_sso_tokens_mock


@pytest.fixture
def mocked_update_refresh_attempted_at():
    with patch.object(
        keyring, "update_refresh_attempted_at"
    ) as update_refresh_attempted_at_mock:
        yield update_refresh_attempted_at_mock


class TestInitialiseApi:
    def setup_method(self):
        # Reset the module-level config before each test
        init_module._cli_config = None

    def test_initialise_api_sets_cli_config(self, mocked_get_access_token):
        """Assert that initialise_api stores a CliConfig with expected attributes."""
        mocked_get_access_token.return_value = None

        config_attrs = [
            "rate_limit",
            "error_retry_max",
            "error_retry_backoff",
            "error_retry_codes",
            "error_retry_cb",
        ]

        # Before initialise_api, module-level config should be None
        assert init_module._cli_config is None

        config = initialise_api()
        assert isinstance(config, CliConfig)
        assert all(hasattr(config, attr) for attr in config_attrs)

        # After initialise_api, module-level config should be set
        assert init_module._cli_config is config

    def test_initialise_api_with_refreshable_access_token_set(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        mocked_should_refresh_access_token.return_value = True

        # Ensure keyring is enabled for this test
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(host="https://example.com")

        assert config.headers == {"Authorization": "Bearer new_access_token"}
        mocked_refresh_access_token.assert_called_once()
        mocked_store_sso_tokens.assert_called_once_with(
            "https://example.com", "new_access_token", "new_refresh_token"
        )

    def test_initialise_api_with_recently_refreshed_access_token_and_empty_basic_auth_set(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        auth_header = CliConfig().get_basic_auth_token()

        # Ensure keyring is enabled for this test
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(
                host="https://example.com", headers={"Authorization": auth_header}
            )

        assert config.headers == {"Authorization": "Bearer dummy_access_token"}
        assert config.username == ""
        assert config.password == ""
        mocked_refresh_access_token.assert_not_called()
        mocked_store_sso_tokens.assert_not_called()
        mocked_update_refresh_attempted_at.assert_not_called()

    def test_initialise_api_with_recently_refreshed_access_token_and_present_basic_auth(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        temp_config = CliConfig(username="username", password="password")
        auth_header = temp_config.get_basic_auth_token()
        config = initialise_api(
            host="https://example.com", headers={"Authorization": auth_header}
        )

        assert config.headers == {"Authorization": auth_header}
        assert config.username == "username"
        assert config.password == "password"
        mocked_refresh_access_token.assert_not_called()
        mocked_store_sso_tokens.assert_not_called()
        mocked_update_refresh_attempted_at.assert_not_called()

    def test_initialise_api_skips_keyring_when_env_var_set(
        self,
        mocked_get_access_token,
    ):
        """Verify keyring returns None when CLOUDSMITH_NO_KEYRING=1."""
        mocked_get_access_token.return_value = None
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            config = initialise_api(host="https://example.com", key="test_api_key")

        # get_access_token is called but returns None due to internal guard
        mocked_get_access_token.assert_called_once()
        # API key should be used instead
        assert config.api_key["X-Api-Key"] == "test_api_key"

    def test_initialise_api_uses_keyring_when_env_var_not_set(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
    ):
        """Verify keyring is accessed when CLOUDSMITH_NO_KEYRING is not set."""
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(host="https://example.com")

        # Keyring should be accessed
        mocked_get_access_token.assert_called_once()
        assert config.headers == {"Authorization": "Bearer dummy_access_token"}

    def test_initialise_api_falls_back_to_api_key_when_sso_refresh_fails(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        """Verify API key is used as fallback when SSO token refresh fails."""
        from ..api.exceptions import ApiException

        # Simulate SSO token refresh failure
        mocked_should_refresh_access_token.return_value = True
        mocked_refresh_access_token.side_effect = ApiException(
            status=401, detail="Unauthorized"
        )

        # Ensure keyring is enabled for this test
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(host="https://example.com", key="fallback_api_key")

        # Should not use expired SSO token
        assert (
            "Authorization" not in config.headers
            or config.headers.get("Authorization") != "Bearer dummy_access_token"
        )
        # Should fall back to API key
        assert config.api_key["X-Api-Key"] == "fallback_api_key"
        mocked_update_refresh_attempted_at.assert_called_once()
        mocked_store_sso_tokens.assert_not_called()

    def test_initialise_api_no_auth_when_sso_refresh_fails_without_api_key(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        """Verify expired SSO token is not used when refresh fails and no API key available."""
        from ..api.exceptions import ApiException

        # Simulate SSO token refresh failure
        mocked_should_refresh_access_token.return_value = True
        mocked_refresh_access_token.side_effect = ApiException(
            status=401, detail="Unauthorized"
        )

        # Ensure keyring is enabled for this test
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(host="https://example.com", key=None)

        # Should not use expired SSO token
        assert (
            "Authorization" not in config.headers
            or config.headers.get("Authorization") != "Bearer dummy_access_token"
        )
        # Should not have API key either
        assert "X-Api-Key" not in config.api_key
        mocked_update_refresh_attempted_at.assert_called_once()
        mocked_store_sso_tokens.assert_not_called()

    def test_initialise_api_uses_direct_access_token_when_keyring_disabled(
        self,
        mocked_get_access_token,
    ):
        """Verify a directly provided access_token is used even when keyring is disabled.

        This is the critical path for --request-api-key with CLOUDSMITH_NO_KEYRING=1.
        The SSO callback provides the access token directly, bypassing keyring storage.
        """
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            config = initialise_api(
                host="https://example.com",
                access_token="sso_direct_token_abc123",
            )

        # Keyring should NOT be accessed
        mocked_get_access_token.assert_not_called()
        # The directly provided access token should be used as Bearer auth
        assert config.headers == {"Authorization": "Bearer sso_direct_token_abc123"}

    def test_initialise_api_direct_access_token_takes_precedence_over_keyring(
        self,
        mocked_get_access_token,
        mocked_should_refresh_access_token,
    ):
        """Verify a directly provided access_token takes precedence over keyring."""
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            config = initialise_api(
                host="https://example.com",
                access_token="direct_token_xyz",
            )

        # Keyring should NOT be accessed because we have a direct token
        mocked_get_access_token.assert_not_called()
        # The direct access token should be used
        assert config.headers == {"Authorization": "Bearer direct_token_xyz"}

    def test_initialise_api_direct_access_token_skips_refresh(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        """Verify a directly provided access_token skips the refresh cycle entirely.

        When the SSO callback provides a fresh token
        directly (e.g. for --request-api-key with CLOUDSMITH_NO_KEYRING=1),
        we must NOT attempt to refresh it. The refresh path would fail because
        there is no refresh_token in keyring, clearing the access_token and
        leaving zero authentication.
        """
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            config = initialise_api(
                host="https://example.com",
                access_token="fresh_sso_token",
            )

        # Keyring lookup should be skipped (direct token provided)
        mocked_get_access_token.assert_not_called()
        # should_refresh_access_token is called but returns False
        # due to internal should_use_keyring() guard
        mocked_should_refresh_access_token.assert_called_once()
        # Refresh logic should NOT be triggered
        mocked_refresh_access_token.assert_not_called()
        mocked_store_sso_tokens.assert_not_called()
        mocked_update_refresh_attempted_at.assert_not_called()
        # The fresh SSO token should be used as-is
        assert config.headers == {"Authorization": "Bearer fresh_sso_token"}
