# Copyright 2026 Cloudsmith Ltd
"""API - Shared client for v2 endpoints not yet present in cloudsmith_api."""

import json
from urllib.parse import urlparse

import cloudsmith_api

from .. import ratelimits
from ..credentials.models import CredentialResult
from ..rest import RestClient
from .exceptions import ApiException, catch_raise_api_exception

REQUEST_TIMEOUT_SECONDS = 30


class V2Client:
    """Small client for v2 endpoints not yet present in cloudsmith_api."""

    def __init__(self, credential):
        self.config = cloudsmith_api.Configuration()
        self.credential = credential
        self.rest_client = RestClient(
            error_retry_cb=getattr(self.config, "error_retry_cb", None),
            respect_retry_after_header=getattr(self.config, "rate_limit", True),
        )


def get_client(credential: CredentialResult | None):
    """Get a v2 API client for the configured host and the resolved credential."""
    return V2Client(credential)


def _build_url(config, *parts):
    host = (config.host or "").rstrip("/")
    suffix = "/".join(p.strip("/") for p in parts if p)
    return f"{host}/v2/{suffix}/"


def _build_headers(client):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    headers.update(getattr(client.config, "headers", None) or {})

    user_agent = getattr(client.config, "user_agent", None)
    if user_agent:
        headers["User-Agent"] = user_agent

    if client.credential:
        headers.update(client.credential.auth_headers())

    return headers


def _is_same_origin(url, host):
    target, configured = urlparse(url), urlparse(host or "")
    return (target.scheme, target.netloc) == (configured.scheme, configured.netloc)


def _timeout(method):
    # A retry after a read timeout sends the request again, so a POST gets
    # only a connect timeout and cannot create a second entry.
    if method.upper() == "POST":
        return (REQUEST_TIMEOUT_SECONDS, None)
    return REQUEST_TIMEOUT_SECONDS


def request(client, method, *path_parts, query_params=None, body=None):
    """Send a request to the v2 endpoint that `path_parts` names."""
    url = _build_url(client.config, *path_parts)
    return request_url(client, method, url, query_params=query_params, body=body)


def request_url(client, method, url, query_params=None, body=None):
    """Send a request to an absolute v2 URL, such as a pagination link."""
    if not _is_same_origin(url, client.config.host):
        raise ApiException(status=0, detail=f"Refusing to send credentials to {url}")

    with catch_raise_api_exception():
        response = client.rest_client.request(
            method,
            url,
            query_params=query_params,
            headers=_build_headers(client),
            body=body,
            _request_timeout=_timeout(method),
        )

    ratelimits.maybe_rate_limit(client, response.getheaders())
    return response


def response_json(response):
    """Decode a response body, or an empty dict if there is none."""
    if not response.data:
        return {}
    return json.loads(response.data)
