"""API - Exceptions."""

import contextlib
import http.client

from cloudsmith_sdk import CloudsmithApiError


class ApiException(Exception):
    """Exception raised by the Cloudsmith API."""

    def __init__(self, status, detail=None, headers=None, body=None, fields=None):
        """Create a new APIException."""
        super().__init__()
        self.status = status
        if status == 422:
            self.status_description = "Unprocessable Entity"
        else:
            self.status_description = http.client.responses.get(
                status, "Unknown Status"
            )
        self.detail = detail
        self.headers = headers or {}
        self.body = body
        self.fields = fields or {}


@contextlib.contextmanager
def catch_raise_api_exception():
    """Context manager that translates upstream API exceptions."""
    try:
        yield
    except CloudsmithApiError as exc:
        detail = exc.detail or exc.reason
        fields = exc.fields
        raise ApiException(
            exc.status_code,
            detail=detail,
            headers=exc.headers,
            body=exc.body,
            fields=fields,
        )


class TwoFactorRequiredException(Exception):
    def __init__(self, two_factor_token):
        self.two_factor_token = two_factor_token
        super().__init__("Two-factor authentication is required")
