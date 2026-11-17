"""Tests for the webserver module."""

import contextlib
import os
from http.server import HTTPServer
from unittest.mock import MagicMock, PropertyMock, patch

import click
import cloudsmith_api
import pytest
from keyring.errors import KeyringError

from ...core.api.exceptions import ApiException
from ..webserver import (
    TWO_FACTOR_PROMPT,
    AuthenticationWebRequestHandler,
    AuthenticationWebServer,
    _clear_echoed_input,
    _display_rows,
)


@pytest.fixture
def server():
    """Create a server. Other servers that the test creates also bind no socket."""

    def _fake_http_server_init(self, *args, **kwargs):
        self.socket = MagicMock()

    with patch.object(HTTPServer, "__init__", _fake_http_server_init):
        yield AuthenticationWebServer(("localhost", 0), MagicMock())


class TestAuthenticationWebServer:
    """Tests for AuthenticationWebServer SAML token storage."""

    def test_sso_access_token_initialized_to_none(self, server):
        """Verify sso_access_token is initialized to None."""
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

    def test_refresh_api_config_keeps_ssl_verify(self):
        with patch.object(AuthenticationWebServer, "__init__", lambda *a, **kw: None):
            server = AuthenticationWebServer.__new__(AuthenticationWebServer)
            server.sso_access_token = None
            server.api_opts = cloudsmith_api.Configuration()
            server.api_opts.verify_ssl = False

            with patch("cloudsmith_cli.cli.webserver.initialise_api") as mock_init_api:
                server.refresh_api_config_after_auth()

        assert mock_init_api.call_args.kwargs["ssl_verify"] is False


class TestAuthenticationWebServerCallback:
    """Tests for how the server binds a callback to this login."""

    def test_each_login_has_its_own_state(self, server):
        other_login = AuthenticationWebServer(("localhost", 0), MagicMock())
        assert other_login.state != server.state

    def test_own_state_is_expected(self, server):
        assert server.is_expected_state(server.state)

    @pytest.mark.parametrize("received_state", ["", "wrong_státe"])
    def test_other_states_are_not_expected(self, server, received_state):
        assert not server.is_expected_state(received_state)

    def test_wait_for_callback_waits_past_rejected_callbacks(self, server):
        def accept_second_callback():
            server.callback_received = server.handle_request.call_count == 2

        with patch.object(
            server, "handle_request", side_effect=accept_second_callback
        ) as mock_handle_request:
            server.wait_for_callback()

        assert mock_handle_request.call_count == 2

    def test_only_an_error_in_the_callback_stops_the_wait(self, server):
        with (
            patch.object(server, "get_request", return_value=(MagicMock(), None)),
            patch.object(server, "process_request", side_effect=BrokenPipeError),
        ):
            server._handle_request_noblock()

            server.callback_received = True
            with pytest.raises(BrokenPipeError):
                server._handle_request_noblock()

    def test_idle_connection_times_out(self):
        connection = MagicMock()
        handler = AuthenticationWebRequestHandler.__new__(
            AuthenticationWebRequestHandler
        )
        handler.request = connection

        handler.setup()

        connection.settimeout.assert_called_once_with(handler.timeout)


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

    @pytest.mark.parametrize(
        "store_result,message",
        [
            (
                {"return_value": False},
                "SAML tokens not stored (CLOUDSMITH_NO_KEYRING is set)",
            ),
            (
                {"side_effect": KeyringError("no prompt")},
                "SAML tokens not stored: no prompt",
            ),
        ],
    )
    def test_message_shown_when_tokens_not_stored(
        self, mock_handler, store_result, message
    ):
        """Verify message is shown when store_sso_tokens does not store tokens."""
        with (
            patch(
                "cloudsmith_cli.cli.webserver.store_sso_tokens", **store_result
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

            # store_sso_tokens should be called
            mock_store.assert_called_once()

            # Message should be displayed to stderr
            mock_echo.assert_called_once_with(message, err=True)

    def test_access_token_stored_on_server_instance(self, mock_handler):
        """Verify the SAML access token is stored on the server instance for direct use."""
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
            assert mock_handler.server_instance.callback_received is True

    def test_callback_with_unexpected_state_is_rejected(self, mock_handler):
        """Verify forged callbacks store nothing, warn once and do not end the login."""
        server = mock_handler.server_instance
        server.is_expected_state.return_value = False
        server.callback_received = False
        server.callback_rejected = False
        with (
            patch("cloudsmith_cli.cli.webserver.store_sso_tokens") as mock_store,
            patch("click.secho") as mock_secho,
            patch.object(mock_handler, "_return_error_response") as mock_error,
            patch.object(
                AuthenticationWebRequestHandler,
                "query_data",
                new_callable=PropertyMock,
                return_value={"access_token": "attacker_token", "state": "wrong"},
            ),
        ):
            mock_handler.do_GET()
            mock_handler.do_GET()

        server.is_expected_state.assert_called_with("wrong")
        mock_store.assert_not_called()
        assert mock_error.call_count == 2
        mock_secho.assert_called_once()
        assert server.callback_received is False


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
            patch("cloudsmith_cli.cli.webserver._clear_echoed_input") as mock_clear,
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
            manager.attach_mock(mock_clear, "clear")
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

    def test_echoed_input_is_cleared_before_each_exchange(self, two_factor_handler):
        """Verify each entered value is cleared, including rejected ones."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[
                ApiException(422),
                ("access_token_123", "refresh_token_123"),
            ],
            prompt_side_effect=["oops-my-password", "123456"],
        ) as manager:
            two_factor_handler.do_GET()

            calls = [
                name
                for name, _, _ in manager.mock_calls
                if name in ("prompt", "clear", "exchange")
            ]
            assert calls == ["prompt", "clear", "exchange"] * 2
            assert [c.args for c in manager.clear.call_args_list] == [
                (TWO_FACTOR_PROMPT, "oops-my-password"),
                (TWO_FACTOR_PROMPT, "123456"),
            ]

    def test_rejection_message_leaves_out_the_status_code(
        self, two_factor_handler, capsys
    ):
        """Verify a rejected code shows a plain message, not the HTTP error."""
        with self._patched(
            two_factor_handler,
            exchange_side_effect=[
                ApiException(422, detail="Invalid input."),
                ("access_token_123", "refresh_token_123"),
            ],
            prompt_side_effect=["000000", "123456"],
        ):
            two_factor_handler.do_GET()

        err = capsys.readouterr().err
        assert "That code was rejected. Please try again." in err
        assert "422" not in err
        assert "Invalid input" not in err

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


class TestClearEchoedInput:
    """Tests for clearing the echoed 2FA input from the terminal."""

    CLEAR_LINE = "\x1b[1A\x1b[2K"

    @staticmethod
    @contextlib.contextmanager
    def _terminal(isatty=True, columns=80):
        """Fake a terminal on stdin and stderr, capturing what stderr receives."""
        written = []
        stream = MagicMock()
        stream.isatty.return_value = isatty
        stream.fileno.return_value = 2
        stream.write.side_effect = written.append
        with (
            patch("sys.stdin", stream),
            patch("sys.stderr", stream),
            patch(
                "os.get_terminal_size",
                return_value=os.terminal_size((columns, 24)),
            ) as get_size,
        ):
            yield written, get_size

    def test_erases_the_prompt_line_entirely(self):
        """Verify the prompt line is erased without writing anything in its place."""
        with self._terminal(columns=120) as (written, _):
            _clear_echoed_input(TWO_FACTOR_PROMPT, "oops-my-password")

        assert "".join(written) == self.CLEAR_LINE

    def test_clears_every_row_of_wrapped_input(self):
        """Verify input wider than the terminal is cleared from every row."""
        value = "x" * 100
        # The prompt and its ": " suffix are 71 columns, so 171 columns over 4 rows.
        with self._terminal(columns=50) as (written, _):
            _clear_echoed_input(TWO_FACTOR_PROMPT, value)

        assert "".join(written).count(self.CLEAR_LINE) == 4

    def test_uses_the_width_of_stderr(self):
        """Verify the width comes from stderr, which still is a terminal when
        stdout is redirected."""
        with self._terminal() as (_, get_size):
            _clear_echoed_input(TWO_FACTOR_PROMPT, "123456")

        get_size.assert_called_once_with(2)

    def test_falls_back_to_80_columns(self):
        """Verify a terminal whose size can't be read is treated as 80 wide."""
        with self._terminal() as (written, get_size):
            get_size.side_effect = OSError
            # 71 + 10 = 81 columns, so 2 rows at 80 columns.
            _clear_echoed_input(TWO_FACTOR_PROMPT, "x" * 10)

        assert "".join(written).count(self.CLEAR_LINE) == 2

    def test_escape_codes_are_written_when_colour_is_off(self):
        """Verify --color never or NO_COLOR doesn't stop the line being erased."""
        with self._terminal() as (written, _):
            with click.Context(click.Command("auth"), color=False):
                _clear_echoed_input(TWO_FACTOR_PROMPT, "123456")

        assert "".join(written) == self.CLEAR_LINE

    def test_does_nothing_without_a_tty(self):
        """Verify no escape codes are written when not attached to a terminal."""
        with self._terminal(isatty=False) as (written, _):
            _clear_echoed_input(TWO_FACTOR_PROMPT, "123456")

        assert not written


class TestDisplayRows:
    """Tests for counting the rows that echoed text takes up."""

    @pytest.mark.parametrize(
        ("text", "rows"),
        [
            ("", 1),
            ("x" * 10, 1),
            ("x" * 10 + "y", 2),
            ("x" * 25, 3),
        ],
    )
    def test_ascii(self, text, rows):
        """Verify text exactly as wide as the terminal stays on one row."""
        assert _display_rows(text, 10) == rows

    def test_wide_characters_take_two_columns(self):
        """Verify full-width characters count double."""
        assert _display_rows("界" * 5, 10) == 1
        assert _display_rows("界" * 6, 10) == 2

    def test_wide_character_that_does_not_fit_moves_to_the_next_row(self):
        """Verify a wide character never splits across the edge of the row."""
        # 9 columns used, so the next 2-column character starts row 2.
        assert _display_rows("x" * 9 + "界" * 5, 10) == 2
        assert _display_rows("x" * 9 + "界" * 6, 10) == 3

    def test_combining_characters_take_no_columns(self):
        """Verify combining marks don't push text onto extra rows."""
        assert _display_rows("e\u0301" * 10, 10) == 1

    def test_tabs_move_to_the_next_stop(self):
        """Verify a tab advances to the next multiple of 8 columns."""
        assert _display_rows("x\t" + "y" * 8, 16) == 1
        assert _display_rows("x\t" + "y" * 9, 16) == 2
