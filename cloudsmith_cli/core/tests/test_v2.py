# Copyright 2026 Cloudsmith Ltd
"""Tests for the shared v2 API client."""

import json

import httpretty
import httpretty.core
import pytest

from .. import keyring
from ..api import v2
from ..api.exceptions import ApiException
from ..api.init import initialise_api
from ..credentials.models import CredentialResult
from ..rest import RestClient

API_HOST = "https://api.example.com"
RESOURCE_URL = f"{API_HOST}/v2/things/"


@pytest.fixture(autouse=True)
def _setup_api(monkeypatch):
    """Initialise the SDK Configuration and stub keyring lookups."""
    monkeypatch.setattr(keyring, "get_access_token", lambda host, profile=None: None)
    monkeypatch.setattr(keyring, "get_refresh_token", lambda host, profile=None: None)
    monkeypatch.setattr(
        keyring, "should_refresh_access_token", lambda host, profile=None: False
    )
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )
    initialise_api(
        host=API_HOST,
        credential=CredentialResult(api_key="test-api-key", source_name="test"),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v2/things/?page=2",
        "https://other.example.com/v2/things/?page=2",
    ],
)
@httpretty.activate(allow_net_connect=False)
def test_request_url_does_not_send_credentials_to_another_origin(url):
    """A URL on another scheme or host does not get the API key."""
    with pytest.raises(ApiException):
        v2.request_url(v2.get_client(), "GET", url)

    assert not httpretty.latest_requests()


@httpretty.activate(allow_net_connect=False)
def test_request_does_not_send_the_api_key_through_a_redirect_to_another_host():
    """A redirect to another host does not get the API key."""
    other_url = "https://other.example.com/v2/things/"
    httpretty.register_uri(
        httpretty.GET, RESOURCE_URL, status=302, location=other_url, body=""
    )
    httpretty.register_uri(httpretty.GET, other_url, body="{}", status=200)

    v2.request(v2.get_client(), "GET", "things")

    assert "X-Api-Key" not in httpretty.last_request().headers


@httpretty.activate(allow_net_connect=False)
def test_request_sets_a_timeout(monkeypatch):
    """A stalled API does not block the CLI forever."""
    httpretty.register_uri(
        httpretty.GET, RESOURCE_URL, body=json.dumps({"results": []}), status=200
    )
    timeouts = []
    original_request = RestClient.request

    def _record_timeout(self, *args, **kwargs):
        timeouts.append(kwargs.get("_request_timeout"))
        return original_request(self, *args, **kwargs)

    monkeypatch.setattr(RestClient, "request", _record_timeout)

    v2.request(v2.get_client(), "GET", "things")

    assert timeouts == [v2.REQUEST_TIMEOUT_SECONDS]
