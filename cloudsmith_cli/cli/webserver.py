import json
from functools import cached_property
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlparse

import click
import requests

from ..core.keyring import store_sso_tokens


class AuthenticationWebServer(HTTPServer):
    def __init__(
        self, server_address, RequestHandlerClass, bind_and_activate=True, **kwargs
    ):
        self.api_host = kwargs.get("api_host")
        self.owner = kwargs.get("owner")

        super().__init__(
            server_address, RequestHandlerClass, bind_and_activate=bind_and_activate
        )

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(
            request, client_address, self, api_host=self.api_host, owner=self.owner
        )


class AuthenticationWebRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server, **kwargs):
        self.api_host = kwargs.get("api_host")
        self.owner = kwargs.get("owner")

        super().__init__(request, client_address, server)

    @cached_property
    def url(self):
        return urlparse(self.path)

    @cached_property
    def query_data(self):
        return dict(parse_qsl(self.url.query))

    def get_response(self):
        return json.dumps(
            {
                "query_data": self.query_data,
            }
        )

    def _exchange_2fa_token(self, two_factor_token):
        totp_token = click.prompt(
            "Please enter your 2FA token", hide_input=True, type=str
        )

        exchange_data = {"two_factor_token": two_factor_token, "totp_token": totp_token}
        exchange_url = "{api_host}/user/two-factor/".format(api_host=self.api_host)

        exchange_response = requests.post(exchange_url, data=exchange_data, timeout=5)

        exchange_data = exchange_response.json()
        access_token = exchange_data.get("access_token")
        refresh_token = exchange_data.get("refresh_token")

        return (access_token, refresh_token)

    def _return_response(self, message=None):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        if not message:
            message = self.get_response()

        self.wfile.write(message.encode("utf-8"))

    def _return_success_response(self):
        self._return_response()

    def _return_error_response(self):
        self._return_response()

    def do_GET(self):
        access_token = self.query_data.get("access_token")
        refresh_token = self.query_data.get("refresh_token")
        two_factor_token = self.query_data.get("two_factor_token")

        if access_token:
            store_sso_tokens(access_token, refresh_token)

            self._return_success_response()
            return

        if two_factor_token:
            access_token, refresh_token = self._exchange_2fa_token(two_factor_token)
            store_sso_tokens(access_token, refresh_token)

            self._return_success_response()
            return

        self._return_error_response()
        return
