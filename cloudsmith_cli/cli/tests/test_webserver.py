"""Tests for the webserver module."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ..webserver import AuthenticationWebRequestHandler, AuthenticationWebServer


class TestAuthenticationWebServer:
    """Tests for AuthenticationWebServer."""

    def test_no_keyring_attribute_set_from_kwargs(self):
        """Verify no_keyring is set from kwargs."""
        with patch("socket.socket"):
            with patch.object(AuthenticationWebServer, "server_bind"):
                with patch.object(AuthenticationWebServer, "server_activate"):
                    server = AuthenticationWebServer(
                        ("127.0.0.1", 12400),
                        AuthenticationWebRequestHandler,
                        bind_and_activate=False,
                        owner="testorg",
                        no_keyring=True,
                    )
                    assert server.no_keyring is True

    def test_no_keyring_defaults_to_false(self):
        """Verify no_keyring defaults to False when not provided."""
        with patch("socket.socket"):
            with patch.object(AuthenticationWebServer, "server_bind"):
                with patch.object(AuthenticationWebServer, "server_activate"):
                    server = AuthenticationWebServer(
                        ("127.0.0.1", 12400),
                        AuthenticationWebRequestHandler,
                        bind_and_activate=False,
                        owner="testorg",
                    )
                    assert server.no_keyring is False


class TestAuthenticationWebRequestHandlerNoKeyring:
    """Tests for AuthenticationWebRequestHandler with no_keyring flag."""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock handler with controlled attributes."""
        with patch.object(
            AuthenticationWebRequestHandler, "__init__", lambda *args, **kwargs: None
        ):
            handler = AuthenticationWebRequestHandler.__new__(
                AuthenticationWebRequestHandler
            )
            handler.server_instance = MagicMock()
            handler.server_instance.api_host = "https://api.cloudsmith.io"
            handler.refresh_api_on_success = False
            handler.session = MagicMock()
            handler.debug = False
            return handler

    def test_store_sso_tokens_called_when_no_keyring_false(self, mock_handler):
        """Verify store_sso_tokens is called when no_keyring is False."""
        mock_handler.no_keyring = False

        with patch("cloudsmith_cli.cli.webserver.store_sso_tokens") as mock_store:
            with patch.object(mock_handler, "_return_success_response"):
                with patch.object(
                    AuthenticationWebRequestHandler,
                    "query_data",
                    new_callable=PropertyMock,
                ) as mock_query:
                    with patch.object(
                        AuthenticationWebRequestHandler,
                        "api_host",
                        new_callable=PropertyMock,
                    ) as mock_host:
                        mock_query.return_value = {
                            "access_token": "test_access_token",
                            "refresh_token": "test_refresh_token",
                        }
                        mock_host.return_value = "https://api.cloudsmith.io"

                        mock_handler.do_GET()

                        mock_store.assert_called_once_with(
                            "https://api.cloudsmith.io",
                            "test_access_token",
                            "test_refresh_token",
                        )

    def test_store_sso_tokens_not_called_when_no_keyring_true(self, mock_handler):
        """Verify store_sso_tokens is NOT called when no_keyring is True."""
        mock_handler.no_keyring = True

        with patch("cloudsmith_cli.cli.webserver.store_sso_tokens") as mock_store:
            with patch("click.echo") as mock_echo:
                with patch.object(mock_handler, "_return_success_response"):
                    with patch.object(
                        AuthenticationWebRequestHandler,
                        "query_data",
                        new_callable=PropertyMock,
                    ) as mock_query:
                        with patch.object(
                            AuthenticationWebRequestHandler,
                            "api_host",
                            new_callable=PropertyMock,
                        ) as mock_host:
                            mock_query.return_value = {
                                "access_token": "test_access_token",
                                "refresh_token": "test_refresh_token",
                            }
                            mock_host.return_value = "https://api.cloudsmith.io"

                            mock_handler.do_GET()

                            # store_sso_tokens should NOT be called
                            mock_store.assert_not_called()

                            # Message should be displayed to stderr
                            mock_echo.assert_called_once_with(
                                "SSO tokens not stored (--no-keyring enabled)",
                                err=True,
                            )
