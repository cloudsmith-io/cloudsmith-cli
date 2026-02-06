"""Tests for the auth command."""

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

    def test_auth_command_invokes_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify auth command creates AuthenticationWebServer."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called
        mock_auth_server.assert_called_once()

    def test_auth_command_opens_browser(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify auth command opens browser with IDP URL."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify browser was opened
        mock_webbrowser.open.assert_called_once_with("https://idp.example.com/saml")

    def test_auth_command_passes_owner_to_webserver(
        self,
        runner,
        mock_saml_session,
        mock_get_idp_url,
        mock_webbrowser,
        mock_auth_server,
    ):
        """Verify owner is passed to AuthenticationWebServer."""
        runner.invoke(
            authenticate,
            ["--owner", "testorg"],
            catch_exceptions=False,
        )

        # Verify AuthenticationWebServer was called with owner
        mock_auth_server.assert_called_once()
        call_kwargs = mock_auth_server.call_args.kwargs
        assert call_kwargs.get("owner") == "testorg"
