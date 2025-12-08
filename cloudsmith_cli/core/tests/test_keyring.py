import getpass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import keyring
import pytest
from freezegun import freeze_time
from keyring.errors import KeyringError

from ..keyring import (
    get_access_token,
    get_refresh_attempted_at,
    get_refresh_token,
    should_refresh_access_token,
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
        refresh_attempted_at = datetime.utcnow().isoformat()
        store_sso_tokens(self.api_host, "access_token", "refresh_token")

        assert mock_set_password.call_count == 3
        mock_set_password.assert_any_call(
            "cloudsmith_cli-access_token-https://example.com",
            "test_user",
            "access_token",
        )
        mock_set_password.assert_any_call(
            "cloudsmith_cli-access_token_refresh_attempted_at-https://example.com",
            "test_user",
            refresh_attempted_at,
        )
        mock_set_password.assert_any_call(
            "cloudsmith_cli-refresh_token-https://example.com",
            "test_user",
            "refresh_token",
        )
