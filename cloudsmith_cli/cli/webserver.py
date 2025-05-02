import html
import os
import socket
from functools import cached_property
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, unquote, urlparse

import click

from ..core.api.exceptions import ApiException
from ..core.keyring import store_sso_tokens
from .saml import exchange_2fa_token


def get_template_path(template_name):
    """Get the absolute path to a template file."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "templates", template_name)


def render_template(template_name, **context):
    """
    Render a template with the given context.

    Args:
        template_name: Name of the template file
        context: Dictionary of variables to replace in the template

    Returns:
        Rendered HTML content
    """
    template_path = get_template_path(template_name)

    with open(template_path, encoding="utf-8") as file:
        content = file.read()

    # Replace placeholders with context values
    for key, value in context.items():
        placeholder = f"<!-- {key.upper()}_PLACEHOLDER -->"
        content = content.replace(placeholder, value if value else "")

    return content


class AuthenticationWebServer(HTTPServer):
    def __init__(
        self, server_address, RequestHandlerClass, bind_and_activate=True, **kwargs
    ):
        self.api_host = kwargs.get("api_host")
        self.owner = kwargs.get("owner")
        self.session = kwargs.get("session")
        self.debug = kwargs.get("debug", False)
        self.exception = None

        super().__init__(
            server_address, RequestHandlerClass, bind_and_activate=bind_and_activate
        )

        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def finish_request(self, request, client_address):
        self.RequestHandlerClass(
            request,
            client_address,
            self,
            api_host=self.api_host,
            owner=self.owner,
            debug=self.debug,
            session=self.session,
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
        self.session = kwargs.get("session")

        super().__init__(request, client_address, server)

    def _return_response(self, status=200, message=None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        self.wfile.write(message.encode("utf-8"))

    def _return_success_response(self):
        html_content = render_template("auth_success.html")
        self._return_response(message=html_content)

    def _return_error_response(self, error_message=None):
        error_details = ""
        if error_message:
            safe_error = html.escape(unquote(error_message))
            error_details = f"<p class='error-details'>Error: {safe_error}</p>"

        html_content = render_template("auth_error.html", error_details=error_details)

        self._return_response(
            status=500,
            message=html_content,
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
        error = self.query_data.get("error")

        if error:
            click.secho(
                f"\nAuthentication error received: {unquote(error)}", fg="red", err=True
            )
            self._return_error_response(error)
            return

        try:
            if access_token:
                store_sso_tokens(
                    self.api_host,
                    access_token,
                    refresh_token,
                )

                self._return_success_response()
                return

            if two_factor_token:
                totp_token = click.prompt(
                    "Please enter your 2FA token", hide_input=True, type=str
                )

                access_token, refresh_token = exchange_2fa_token(
                    self.api_host, two_factor_token, totp_token, session=self.session
                )
                store_sso_tokens(
                    self.api_host,
                    access_token,
                    refresh_token,
                )

                click.secho("\nAuthentication complete", fg="green", err=True)
                self._return_success_response()
                return
        except Exception as exc:
            self._return_error_response()
            raise exc

        click.secho("\nNo valid authentication parameters received", fg="red", err=True)
        self._return_error_response()
        return
