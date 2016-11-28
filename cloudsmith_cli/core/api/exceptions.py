"""Cloudsmith CLI - Main command."""
from __future__ import absolute_import, print_function, unicode_literals
import contextlib

try:
    from httplib import responses
except ImportError:
    from http import responses

try:
    import simplejson as json
except:
    import json

from cloudsmith_api.rest import ApiException as _ApiException


class ApiException(Exception):
    """Exception raised by the Cloudsmith API."""
    def __init__(self, status, detail=None, headers=None, body=None,
                 fields=None):
        self.status = status
        self.status_description = responses.get(status, "Unknown Status")
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
        if exc.body:
            try:
                data = json.loads(exc.body)
                detail = data.get('detail', None)
                fields = data.get('fields', None)
            except ValueError:
                detail = None
                fields = None

        raise ApiException(
            exc.status,
            detail=detail,
            headers=exc.headers,
            body=exc.body,
            fields=fields
        )
