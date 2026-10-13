# Copyright 2026 Cloudsmith Ltd
"""Tests for the shared v2 API client."""

import json

import cloudsmith_api
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
API_KEY = CredentialResult(api_key="test-api-key", source_name="test")
SAML_TOKEN = CredentialResult(
    api_key="test-access-token", source_name="keyring", auth_type="bearer"
)


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
    initialise_api(host=API_HOST)


@pytest.mark.parametrize(
    "credential, sent_header, other_header",
    [
        (API_KEY, ("X-Api-Key", "test-api-key"), "Authorization"),
        (SAML_TOKEN, ("Authorization", "Bearer test-access-token"), "X-Api-Key"),
    ],
)
@httpretty.activate(allow_net_connect=False)
def test_request_authenticates_with_the_resolved_credential(
    credential, sent_header, other_header
):
    """An API key and a SAML access token each go in their own header."""
    httpretty.register_uri(httpretty.GET, RESOURCE_URL, body="{}", status=200)

    v2.request(v2.get_client(credential), "GET", "things")

    headers = httpretty.last_request().headers
    assert headers.get(sent_header[0]) == sent_header[1]
    assert other_header not in headers


@httpretty.activate(allow_net_connect=False)
def test_request_without_a_credential_sends_no_auth_headers():
    """An anonymous request sends no API key and no access token."""
    httpretty.register_uri(httpretty.GET, RESOURCE_URL, body="{}", status=200)

    v2.request(v2.get_client(None), "GET", "things")

    headers = httpretty.last_request().headers
    assert "X-Api-Key" not in headers
    assert "Authorization" not in headers


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
        v2.request_url(v2.get_client(API_KEY), "GET", url)

    assert not httpretty.latest_requests()


@pytest.mark.parametrize("credential", [API_KEY, SAML_TOKEN])
@httpretty.activate(allow_net_connect=False)
def test_request_does_not_send_credentials_through_a_redirect_to_another_host(
    credential,
):
    """A redirect to another host does not get the API key or access token."""
    other_url = "https://other.example.com/v2/things/"
    httpretty.register_uri(
        httpretty.GET, RESOURCE_URL, status=302, location=other_url, body=""
    )
    httpretty.register_uri(httpretty.GET, other_url, body="{}", status=200)

    v2.request(v2.get_client(credential), "GET", "things")

    headers = httpretty.last_request().headers
    assert "X-Api-Key" not in headers
    assert "Authorization" not in headers


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

    v2.request(v2.get_client(API_KEY), "GET", "things")

    assert timeouts == [v2.REQUEST_TIMEOUT_SECONDS]


@httpretty.activate(allow_net_connect=False)
def test_request_sends_the_configured_user_agent_and_headers():
    """The --api-user-agent and --api-headers values reach the v2 API."""
    initialise_api(
        host=API_HOST, user_agent="test-agent/1.0", headers={"X-Custom": "value"}
    )
    httpretty.register_uri(httpretty.GET, RESOURCE_URL, body="{}", status=200)

    v2.request(v2.get_client(API_KEY), "GET", "things")

    headers = httpretty.last_request().headers
    assert headers.get("User-Agent") == "test-agent/1.0"
    assert headers.get("X-Custom") == "value"


def test_client_uses_the_configured_proxy_and_ssl_verification(monkeypatch):
    """The --api-proxy and --api-ssl-verify values apply to the v2 client."""
    monkeypatch.setattr(
        cloudsmith_api.Configuration, "_default", cloudsmith_api.Configuration()
    )
    proxy = "http://proxy.example.com:3128"
    initialise_api(host=API_HOST, proxy=proxy, ssl_verify=False)

    session = v2.get_client(API_KEY).rest_client.session

    assert session.proxies == {"http": proxy, "https": proxy}
    assert session.verify is False
