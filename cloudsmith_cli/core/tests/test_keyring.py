import getpass
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, patch

import keyring
import pytest
from freezegun import freeze_time
from keyring.errors import KeyringError

from ..keyring import (
    delete_sso_tokens,
    get_access_token,
    get_refresh_attempted_at,
    get_refresh_token,
    has_sso_tokens,
    should_refresh_access_token,
    should_use_keyring,
    store_access_token,
    store_refresh_token,
    store_sso_tokens,
    update_refresh_attempted_at,
)


@pytest.fixture
def mock_get_user():
    with patch.object(getpass, "getuser", return_value="test_user") as get_user_mock:
        yield get_user_mock


@pytest.fixture
def mock_get_password():
    with patch.object(keyring, "get_password") as get_password_mock:
        yield get_password_mock


@pytest.fixture
def mock_set_password():
    with patch.object(keyring, "set_password") as set_password_mock:
        yield set_password_mock


@pytest.fixture
def mock_delete_password():
    with patch.object(keyring, "delete_password") as delete_password_mock:
        yield delete_password_mock


class TestKeyring:
    api_host = "https://example.com"

    def test_store_access_token(self, mock_get_user, mock_set_password):
        store_access_token(self.api_host, "access_token")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )

    def test_get_access_token(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "access_token"

        assert get_access_token(self.api_host) == "access_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com", "test_user"
        )

    def test_get_access_token_when_error_raised(self, mock_get_user, mock_get_password):
        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_access_token(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token-https://example.com", "test_user"
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_update_refresh_attempted_at(self, mock_get_user, mock_set_password):
        attempted_at = datetime.utcnow().isoformat()

        update_refresh_attempted_at(self.api_host)

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
            attempted_at,
        )

    def test_get_refresh_attempted_at(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = datetime(
            2024, 6, 1, 10, 0, tzinfo=timezone.utc
        ).isoformat()

        assert get_refresh_attempted_at(self.api_host) == datetime(
            2024, 6, 1, hour=10, minute=0, tzinfo=timezone.utc
        )
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    def test_get_refresh_attempted_at_when_keyring_error_raised(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_refresh_attempted_at(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    def test_get_refresh_attempted_at_when_invalid_datetime_returned(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = "invalid_datetime"

        assert get_refresh_attempted_at(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_new_token(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = datetime.utcnow().isoformat()

        assert not should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_token_about_to_expire(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = (
            datetime.utcnow() - timedelta(minutes=30)
        ).isoformat()

        assert not should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_should_refresh_access_token_with_expired_token(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.return_value = (
            datetime.utcnow() - timedelta(minutes=31)
        ).isoformat()

        assert should_refresh_access_token(self.api_host)
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
        )

    def test_store_refresh_token(self, mock_get_user, mock_set_password):
        store_refresh_token(self.api_host, "refresh_token")

        mock_set_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com",
            "test_user",
            "refresh_token",
        )

    def test_get_refresh_token(self, mock_get_user, mock_get_password):
        mock_get_password.return_value = "refresh_token"

        assert get_refresh_token(self.api_host) == "refresh_token"
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com", "test_user"
        )

    def test_get_refresh_token_when_error_raised(
        self, mock_get_user, mock_get_password
    ):
        mock_get_password.side_effect = KeyringError("A keyring error occurred")

        assert get_refresh_token(self.api_host) is None
        mock_get_password.assert_called_once_with(
            "cloudsmith_cli-refresh_token-https://example.com", "test_user"
        )

    @freeze_time("2024-06-01 10:00:00")
    def test_store_sso_tokens(self, mock_get_user, mock_set_password):
        # Ensure keyring is enabled
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            result = store_sso_tokens(self.api_host, "access_token", "refresh_token")

        assert result is True
        assert mock_set_password.call_count == 3
        mock_set_password.assert_any_call(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )
        refresh_key = (
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com"
        )
        mock_set_password.assert_any_call(
            refresh_key,
            "test_user",
            ANY,
        )
        mock_set_password.assert_any_call(
            "cloudsmith_cli-refresh_token-https://example.com",
            "test_user",
            "refresh_token",
        )

    def test_store_sso_tokens_returns_false_when_keyring_disabled(
        self, mock_get_user, mock_set_password
    ):
        """Verify store_sso_tokens returns False when keyring disabled."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            result = store_sso_tokens(self.api_host, "access_token", "refresh_token")

        assert result is False
        mock_set_password.assert_not_called()


class TestShouldUseKeyring:
    """Tests for the should_use_keyring function."""

    def test_returns_true_by_default(self):
        """When env var is not set, keyring should be used."""
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)
        with patch.dict(os.environ, env, clear=True):
            assert should_use_keyring() is True

    @pytest.mark.parametrize(
        "env_value", ["1", "true", "True", "TRUE", "yes", "Yes", "YES"]
    )
    def test_returns_false_when_env_var_is_truthy(self, env_value):
        """Keyring should not be used when CLOUDSMITH_NO_KEYRING is truthy."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": env_value}):
            assert should_use_keyring() is False

    @pytest.mark.parametrize("env_value", ["0", "false", "False", "no", "No", ""])
    def test_returns_true_when_env_var_is_falsy(self, env_value):
        """Keyring should be used when CLOUDSMITH_NO_KEYRING is falsy."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": env_value}):
            assert should_use_keyring() is True


class TestDeleteSsoTokens:
    """Tests for the delete_sso_tokens and has_sso_tokens functions."""

    api_host = "https://example.com"

    def test_delete_sso_tokens(self, mock_get_user, mock_delete_password):
        assert delete_sso_tokens(self.api_host) is True
        assert mock_delete_password.call_count == 3

    def test_delete_sso_tokens_handles_keyring_error(
        self, mock_get_user, mock_delete_password
    ):
        mock_delete_password.side_effect = KeyringError("err")
        assert delete_sso_tokens(self.api_host) is False

    @pytest.mark.parametrize(
        "return_value, expected",
        [
            ("some_token", True),
            (None, False),
            (KeyringError("err"), False),
        ],
    )
    def test_has_sso_tokens(
        self, mock_get_user, mock_get_password, return_value, expected
    ):
        if isinstance(return_value, Exception):
            mock_get_password.side_effect = return_value
        else:
            mock_get_password.return_value = return_value
        assert has_sso_tokens(self.api_host) is expected
