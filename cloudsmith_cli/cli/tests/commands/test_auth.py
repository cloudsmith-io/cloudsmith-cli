"""Tests for the auth command."""

import os
from unittest.mock import MagicMock, patch

import pytest

from ...commands.auth import authenticate


@pytest.fixture
def mock_saml_session():
    """Mock the SAML session creation."""
    with patch(
        "cloudsmith_cli.cli.commands.auth.create_configured_session"
    ) as mock_session:
        mock_session.return_value = MagicMock()
        yield mock_session


@pytest.fixture
def mock_get_idp_url():
    """Mock the IDP URL retrieval."""
    with patch("cloudsmith_cli.cli.commands.auth.get_idp_url") as mock_url:
        mock_url.return_value = "https://idp.example.com/saml"
        yield mock_url


@pytest.fixture
def mock_webbrowser():
    """Mock the webbrowser.open call."""
    with patch("cloudsmith_cli.cli.commands.auth.webbrowser") as mock_browser:
        yield mock_browser


@pytest.fixture
def mock_auth_server():
    """Mock the AuthenticationWebServer."""
    with patch(
        "cloudsmith_cli.cli.commands.auth.AuthenticationWebServer"
    ) as mock_server_class:
        mock_server_instance = MagicMock()
        mock_server_class.return_value = mock_server_instance
        yield mock_server_class


class TestAuthenticateCommand:
    """Tests for the authenticate command."""

    def test_no_keyring_flag_passed_to_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --no-keyring flag is passed to AuthenticationWebServer."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg", "--no-keyring"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called with no_keyring=True
        mock_auth_server.assert_called_once()
        call_kwargs = mock_auth_server.call_args.kwargs
        assert call_kwargs.get("no_keyring") is True

    def test_no_keyring_flag_defaults_to_false(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify no_keyring defaults to False when flag not provided."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called with no_keyring=False
        mock_auth_server.assert_called_once()
        call_kwargs = mock_auth_server.call_args.kwargs
        assert call_kwargs.get("no_keyring") is False

    def test_no_keyring_flag_sets_env_var(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify --no-keyring flag sets CLOUDSMITH_NO_KEYRING env var."""
        # Ensure env var is not set before test
        env_backup = os.environ.copy()
        os.environ.pop("CLOUDSMITH_NO_KEYRING", None)

        try:
            runner.invoke(
                authenticate,
                ["--owner", "testorg", "--no-keyring"],
                catch_exceptions=False,
            )

            # Verify environment variable was set
            assert os.environ.get("CLOUDSMITH_NO_KEYRING") == "1"
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(env_backup)
