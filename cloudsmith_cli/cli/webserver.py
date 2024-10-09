from functools import cached_property
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlparse

import click

from ..core.api.exceptions import ApiException
from ..core.keyring import store_sso_tokens
from .saml import exchange_2fa_token


class AuthenticationWebServer(HTTPServer):
    def __init__(
        self, server_address, RequestHandlerClass, bind_and_activate=True, **kwargs
    ):
        self.api_host = kwargs.get("api_host")
        self.owner = kwargs.get("owner")
        self.debug = kwargs.get("debug", False)
        self.exception = None

        super().__init__(
            server_address, RequestHandlerClass, bind_and_activate=bind_and_activate
        )

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(
            request,
            client_address,
            self,
            api_host=self.api_host,
            owner=self.owner,
            debug=self.debug,
        )

    def _handle_request_noblock(self):
        # override to allow exceptions to bubble up to the CLI
        try:
            request, client_address = self.get_request()
        except OSError:
            return
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except (  # pylint: disable=broad-exception-caught
                Exception,
                ApiException,
            ) as exc:
                self.handle_error(request, client_address)
                self.exception = exc
                self.shutdown_request(request)
            except:  # noqa: E722
                self.shutdown_request(request)
                raise
        else:
            self.shutdown_request(request)

    def handle_error(self, request, client_address):
        if self.debug:
            super().handle_error(request, client_address)

    def shutdown_request(self, request):
        super().shutdown_request(request)
        if self.exception:
            raise self.exception


class AuthenticationWebRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server, **kwargs):
        self.api_host = kwargs.get("api_host")
        self.owner = kwargs.get("owner")
        self.debug = kwargs.get("debug", False)

        super().__init__(request, client_address, server)

    def _return_response(self, status=200, message=None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        self.wfile.write(message.encode("utf-8"))

    def _return_success_response(self):
        self._return_response(
            message="Authentication complete. You may close this window."
        )

    def _return_error_response(self):
        self._return_response(
            status=500,
            message="Authentication failed. Please check output from the CLI for more details.",
        )

    def log_request(self, code="-", size="-"):
        if self.debug:
            return super().log_request(code=code, size=size)

        return

    def log_error(self, format, *args):  # pylint: disable=redefined-builtin
        if self.debug:
            return super().log_error(format, *args)

        return

    @cached_property
    def url(self):
        return urlparse(self.path)

    @cached_property
    def query_data(self):
        return dict(parse_qsl(self.url.query))

    def do_GET(self):
        access_token = self.query_data.get("access_token")
        refresh_token = self.query_data.get("refresh_token")
        two_factor_token = self.query_data.get("two_factor_token")

        try:
            if access_token:
                store_sso_tokens(self.api_host, access_token, refresh_token)

                self._return_success_response()
                return

            if two_factor_token:
                totp_token = click.prompt(
                    "Please enter your 2FA token", hide_input=True, type=str
                )

                access_token, refresh_token = exchange_2fa_token(
                    self.api_host, two_factor_token, totp_token
                )
                store_sso_tokens(self.api_host, access_token, refresh_token)

                self._return_success_response()
                return
        except Exception as exc:
            self._return_error_response()
            raise exc

        self._return_error_response()
        return
