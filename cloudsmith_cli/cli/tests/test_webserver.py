"""Tests for the webserver module."""

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ..webserver import AuthenticationWebRequestHandler


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
        """Verify store_sso_tokens is called when keyring is enabled."""
        # Ensure env var is not set
        env = os.environ.copy()
        env.pop("CLOUDSMITH_NO_KEYRING", None)

        with patch.dict(os.environ, env, clear=True):
            with patch("cloudsmith_cli.cli.webserver.store_sso_tokens") as mock_store:
                with patch(
                    "cloudsmith_cli.cli.webserver.should_use_keyring", return_value=True
                ):
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

    def test_store_sso_tokens_not_called_when_keyring_disabled(self, mock_handler):
        """Verify store_sso_tokens is NOT called when CLOUDSMITH_NO_KEYRING=1."""
        with patch.dict(os.environ, {"CLOUDSMITH_NO_KEYRING": "1"}):
            with patch("cloudsmith_cli.cli.webserver.store_sso_tokens") as mock_store:
                with patch(
                    "cloudsmith_cli.cli.webserver.should_use_keyring",
                    return_value=False,
                ):
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
                                        "SSO tokens not stored (CLOUDSMITH_NO_KEYRING is set)",
                                        err=True,
                                    )
