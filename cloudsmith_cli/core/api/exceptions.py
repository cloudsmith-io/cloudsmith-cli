"""API - Exceptions."""

import contextlib
import http.client
import json

from cloudsmith_api.rest import ApiException as _ApiException


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
    except _ApiException as exc:
        detail = None
        fields = None

        if exc.body:
            try:
                # pylint: disable=no-member
                data = json.loads(exc.body)
                detail = data.get("detail", None)
                fields = data.get("fields", None)
            except ValueError:
                pass

        detail = detail or exc.reason

        raise ApiException(
            exc.status, detail=detail, headers=exc.headers, body=exc.body, fields=fields
        )
