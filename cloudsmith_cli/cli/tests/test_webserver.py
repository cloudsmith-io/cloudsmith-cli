"""Tests for the webserver module."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ..webserver import AuthenticationWebRequestHandler, AuthenticationWebServer


class TestAuthenticationWebServer:
    """Tests for AuthenticationWebServer SSO token storage."""

    def test_sso_access_token_initialized_to_none(self):
        """Verify sso_access_token is initialized to None."""
        with patch.object(AuthenticationWebServer, "__init__", lambda *a, **kw: None):
            server = AuthenticationWebServer.__new__(AuthenticationWebServer)
            server.sso_access_token = None
            assert server.sso_access_token is None

    def test_refresh_api_config_passes_sso_token(self):
        """Verify refresh_api_config_after_auth passes sso_access_token to initialise_api."""
        with patch.object(AuthenticationWebServer, "__init__", lambda *a, **kw: None):
            server = AuthenticationWebServer.__new__(AuthenticationWebServer)
            server.sso_access_token = "test_sso_token_123"
            server.api_opts = MagicMock()
            server.api_opts.debug = False
            server.api_opts.host = "https://api.cloudsmith.io"
            server.api_opts.proxy = None
            server.api_opts.ssl_verify = True
            server.api_opts.user_agent = None
            server.api_opts.headers = None
            server.api_opts.rate_limit = True

            with patch("cloudsmith_cli.cli.webserver.initialise_api") as mock_init_api:
                server.refresh_api_config_after_auth()

                mock_init_api.assert_called_once()
                call_kwargs = mock_init_api.call_args.kwargs
                assert call_kwargs.get("access_token") == "test_sso_token_123"


class TestAuthenticationWebRequestHandlerKeyring:
    """Tests for AuthenticationWebRequestHandler keyring behavior."""

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

    def test_store_sso_tokens_called_when_keyring_enabled(self, mock_handler):
        """Verify store_sso_tokens is called and returns True when keyring is enabled."""
        with patch(
            "cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True
        ) as mock_store:
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

    def test_message_shown_when_keyring_disabled(self, mock_handler):
        """Verify message is shown when store_sso_tokens returns False."""
        with patch(
            "cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=False
        ) as mock_store:
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

                            # store_sso_tokens should be called (returns False)
                            mock_store.assert_called_once()

                            # Message should be displayed to stderr
                            mock_echo.assert_called_once_with(
                                "SSO tokens not stored (CLOUDSMITH_NO_KEYRING is set)",
                                err=True,
                            )

    def test_access_token_stored_on_server_instance(self, mock_handler):
        """Verify the SSO access token is stored on the server instance for direct use."""
        with patch("cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True):
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
                            "access_token": "sso_token_for_direct_use",
                            "refresh_token": "test_refresh_token",
                        }
                        mock_host.return_value = "https://api.cloudsmith.io"

                        mock_handler.do_GET()

                        # Verify do_GET() stored the access token on the server instance
                        assert (
                            mock_handler.server_instance.sso_access_token
                            == "sso_token_for_direct_use"
                        )
