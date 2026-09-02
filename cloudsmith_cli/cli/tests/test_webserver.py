"""Tests for the webserver module."""

import contextlib
from http.server import HTTPServer
from unittest.mock import MagicMock, PropertyMock, patch

import click
import pytest

from ...core.api.exceptions import ApiException
from ..webserver import AuthenticationWebRequestHandler, AuthenticationWebServer


class TestAuthenticationWebServer:
    """Tests for AuthenticationWebServer SSO token storage."""

    def test_sso_access_token_initialized_to_none(self):
        """Verify sso_access_token is initialized to None."""

        def _fake_http_server_init(self, *args, **kwargs):
            self.socket = MagicMock()

        with patch.object(HTTPServer, "__init__", _fake_http_server_init):
            server = AuthenticationWebServer(("localhost", 0), MagicMock())
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
                credential = call_kwargs.get("credential")
                assert credential is not None
                assert credential.api_key == "test_sso_token_123"
                assert credential.auth_type == "bearer"
                assert credential.source_name == "sso"


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
            handler.server_instance.profile = None
            handler.refresh_api_on_success = False
            handler.session = MagicMock()
            handler.debug = False
            return handler

    def test_store_sso_tokens_called_when_keyring_enabled(self, mock_handler):
        """Verify store_sso_tokens is called and returns True when keyring is enabled."""
        with (
            patch(
                "cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True
            ) as mock_store,
            patch.object(mock_handler, "_return_success_response"),
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
            ) as mock_query,
            patch.object(
                AuthenticationWebRequestHandler,
                "api_host",
                new_callable=PropertyMock,
            ) as mock_host,
        ):
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
                profile=None,
            )

    def test_store_sso_tokens_receives_profile(self, mock_handler):
        """Verify store_sso_tokens receives the profile from the server."""
        mock_handler.server_instance.profile = "staging"
        with (
            patch(
                "cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True
            ) as mock_store,
            patch.object(mock_handler, "_return_success_response"),
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
            ) as mock_query,
            patch.object(
                AuthenticationWebRequestHandler,
                "api_host",
                new_callable=PropertyMock,
            ) as mock_host,
        ):
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
                profile="staging",
            )

    def test_message_shown_when_keyring_disabled(self, mock_handler):
        """Verify message is shown when store_sso_tokens returns False."""
        with (
            patch(
                "cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=False
            ) as mock_store,
            patch("click.echo") as mock_echo,
            patch.object(mock_handler, "_return_success_response"),
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
            ) as mock_query,
            patch.object(
                AuthenticationWebRequestHandler,
                "api_host",
                new_callable=PropertyMock,
            ) as mock_host,
        ):
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
        with (
            patch("cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True),
            patch.object(mock_handler, "_return_success_response"),
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
            ) as mock_query,
            patch.object(
                AuthenticationWebRequestHandler,
                "api_host",
                new_callable=PropertyMock,
            ) as mock_host,
        ):
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


class TestAuthenticationWebRequestHandlerResponse:
    """Tests for how responses are written."""

    def test_content_length_is_sent(self):
        """Verify a length is sent so the client can render before the socket closes."""
        with patch.object(
            AuthenticationWebRequestHandler, "__init__", lambda *args, **kwargs: None
        ):
            handler = AuthenticationWebRequestHandler.__new__(
                AuthenticationWebRequestHandler
            )
            handler.wfile = MagicMock()

            with (
                patch.object(handler, "send_response"),
                patch.object(handler, "send_header") as mock_send_header,
                patch.object(handler, "end_headers"),
            ):
                handler._return_response(message="hello")

                headers = dict(call.args for call in mock_send_header.call_args_list)
                assert headers["Content-Length"] == "5"
                assert handler.responded is True

    def test_none_message_defaults_to_empty_body(self):
        """Verify a None response message does not crash response writing."""
        with patch.object(
            AuthenticationWebRequestHandler, "__init__", lambda *args, **kwargs: None
        ):
            handler = AuthenticationWebRequestHandler.__new__(
                AuthenticationWebRequestHandler
            )
            handler.wfile = MagicMock()

            with (
                patch.object(handler, "send_response"),
                patch.object(handler, "send_header") as mock_send_header,
                patch.object(handler, "end_headers"),
            ):
                handler._return_response()

                headers = dict(call.args for call in mock_send_header.call_args_list)
                assert headers["Content-Length"] == "0"
                handler.wfile.write.assert_called_once_with(b"")


class TestAuthenticationWebRequestHandlerTwoFactor:
    """Tests for the 2FA prompt retry behaviour."""

    @pytest.fixture
    def two_factor_handler(self):
        """Create a handler that receives a two-factor token from the IDP."""
        with patch.object(
            AuthenticationWebRequestHandler, "__init__", lambda *args, **kwargs: None
        ):
            handler = AuthenticationWebRequestHandler.__new__(
                AuthenticationWebRequestHandler
            )
            handler.server_instance = MagicMock()
            handler.refresh_api_on_success = False
            handler.session = MagicMock()
            handler.debug = False
            handler.responded = False
            return handler

    @staticmethod
    @contextlib.contextmanager
    def _patched(handler, exchange_side_effect, prompt_side_effect):
        """Patch the 2FA collaborators, recording call order on one manager mock."""
        manager = MagicMock()
        with (
            patch(
                "cloudsmith_cli.cli.webserver.exchange_2fa_token",
                side_effect=exchange_side_effect,
            ) as mock_exchange,
            patch("click.prompt", side_effect=prompt_side_effect) as mock_prompt,
            patch("cloudsmith_cli.cli.webserver.store_sso_tokens", return_value=True),
            patch.object(handler, "_return_success_response") as mock_success,
            patch.object(handler, "_return_error_response") as mock_error,
            patch.object(handler, "_return_two_factor_response") as mock_two_factor,
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
            ) as mock_query,
            patch.object(
                AuthenticationWebRequestHandler,
                "api_host",
                new_callable=PropertyMock,
            ) as mock_host,
        ):
            mock_query.return_value = {"two_factor_token": "two_factor_token_123"}
            mock_host.return_value = "https://api.cloudsmith.io"
            # The real method sets this via _return_response; the mock replaces it.
            mock_two_factor.side_effect = lambda: setattr(handler, "responded", True)
            manager.attach_mock(mock_two_factor, "two_factor_page")
            manager.attach_mock(mock_prompt, "prompt")
            manager.attach_mock(mock_exchange, "exchange")
            manager.attach_mock(mock_success, "success_page")
            manager.attach_mock(mock_error, "error_page")
            yield manager

    def test_browser_told_to_return_to_terminal_before_prompt(self, two_factor_handler):
        """Verify the browser gets a page before the terminal blocks on the prompt."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[("access_token_123", "refresh_token_123")],
            prompt_side_effect=["123456"],
        ) as manager:
            two_factor_handler.do_GET()

            called = [name for name, _, _ in manager.mock_calls]
            assert called.index("two_factor_page") < called.index("prompt")

    def test_no_second_response_after_two_factor_page(self, two_factor_handler):
        """Verify the completed request is not written to a second time."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[("access_token_123", "refresh_token_123")],
            prompt_side_effect=["123456"],
        ) as manager:
            two_factor_handler.do_GET()

            manager.success_page.assert_not_called()
            manager.error_page.assert_not_called()

    def test_no_error_page_when_exchange_fails_after_response(self, two_factor_handler):
        """Verify a failed exchange raises without writing a second response."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=ApiException(500),
            prompt_side_effect=["123456"],
        ) as manager:
            with pytest.raises(ApiException):
                two_factor_handler.do_GET()

            manager.error_page.assert_not_called()

    def test_invalid_code_prompts_again(self, two_factor_handler):
        """Verify a rejected 2FA code prompts again instead of ending the command."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[
                ApiException(401),
                ("access_token_123", "refresh_token_123"),
            ],
            prompt_side_effect=["000000", "123456"],
        ) as manager:
            two_factor_handler.do_GET()

            assert manager.prompt.call_count == 2
            assert manager.exchange.call_count == 2
            assert (
                two_factor_handler.server_instance.sso_access_token
                == "access_token_123"
            )

    def test_prompts_are_unlimited(self, two_factor_handler):
        """Verify rejections keep prompting rather than stopping at a limit."""
        rejections = 25
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[ApiException(401)] * rejections
            + [("access_token_123", "refresh_token_123")],
            prompt_side_effect=["000000"] * rejections + ["123456"],
        ) as manager:
            two_factor_handler.do_GET()

            assert manager.prompt.call_count == rejections + 1
            assert (
                two_factor_handler.server_instance.sso_access_token
                == "access_token_123"
            )

    def test_2fa_prompt_is_not_hidden(self, two_factor_handler):
        """Verify the 2FA code is echoed (not hidden) so users can see typos."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[("access_token_123", "refresh_token_123")],
            prompt_side_effect=["123456"],
        ) as manager:
            two_factor_handler.do_GET()

            assert manager.prompt.call_count == 1
            _, kwargs = manager.prompt.call_args
            assert kwargs.get("hide_input", False) is False

    def test_user_can_abort_the_prompt(self, two_factor_handler):
        """Verify Ctrl-C at the prompt ends the command."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=ApiException(401),
            prompt_side_effect=click.exceptions.Abort(),
        ) as manager:
            with pytest.raises(click.exceptions.Abort):
                two_factor_handler.do_GET()

            manager.error_page.assert_not_called()

    def test_server_error_does_not_retry(self, two_factor_handler):
        """Verify a server-side failure raises without another prompt."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=ApiException(500),
            prompt_side_effect=["123456"],
        ) as manager:
            with pytest.raises(ApiException):
                two_factor_handler.do_GET()

            assert manager.prompt.call_count == 1
