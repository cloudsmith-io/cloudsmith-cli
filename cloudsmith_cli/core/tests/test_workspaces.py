# Copyright 2026 Cloudsmith Ltd
"""Tests for the v2 Workspace API client."""

import json

import httpretty
import httpretty.core
import pytest

from .. import keyring
from ..api import workspaces
from ..api.exceptions import ApiException
from ..api.init import initialise_api
from ..credentials.models import CredentialResult

API_HOST = "https://api.example.com"
DOMAINS_URL = f"{API_HOST}/v2/workspaces/acme/domains/"
CREDENTIAL = CredentialResult(api_key="test-api-key", source_name="test")


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
    monkeypatch.setattr("time.sleep", lambda _: None)
    initialise_api(host=API_HOST)


def _domain(name, domain_type="DOWNLOAD", scope="GLOBAL", repository=None):
    return {
        "domain_name": name,
        "domain_type": domain_type,
        "domain_scope": scope,
        "repository": repository,
    }


@httpretty.activate(allow_net_connect=False)
def test_list_domains_asks_the_configured_api_host():
    """The lookup goes to whichever API host the CLI is configured for."""
    body = {"results": [_domain("dl.example.com")]}
    httpretty.register_uri(
        httpretty.GET, DOMAINS_URL, body=json.dumps(body), status=200
    )

    assert workspaces.list_domains("acme", credential=CREDENTIAL) == body["results"]
    assert httpretty.last_request().headers.get("X-Api-Key") == "test-api-key"


@httpretty.activate(allow_net_connect=False)
def test_list_domains_follows_the_link_header_to_every_page():
    """The endpoint pages with a Link header, so each next page is fetched."""
    first = [_domain("dl.example.com")]
    second = [_domain("upload.example.com", "UPLOAD")]

    def _respond(request, uri, headers):
        if "page=2" in uri:
            return 200, headers, json.dumps({"results": second})
        headers["Link"] = f'<{DOMAINS_URL}?page=2>; rel="next"'
        return 200, headers, json.dumps({"results": first})

    httpretty.register_uri(httpretty.GET, DOMAINS_URL, body=_respond)

    assert workspaces.list_domains("acme", credential=CREDENTIAL) == first + second
    assert len(httpretty.latest_requests()) == 2


@httpretty.activate(allow_net_connect=False)
def test_list_domains_raises_the_api_status_on_failure():
    """A failure reaches the caller as an ApiException carrying the status."""
    httpretty.register_uri(
        httpretty.GET,
        DOMAINS_URL,
        body=json.dumps({"detail": "Not found."}),
        status=404,
    )

    with pytest.raises(ApiException) as raised:
        workspaces.list_domains("acme", credential=CREDENTIAL)

    assert raised.value.status == 404


@httpretty.activate(allow_net_connect=False)
def test_list_domains_does_not_send_credentials_to_another_origin():
    """A next link on another scheme or host does not get the API key."""
    body = {"results": [_domain("dl.example.com")]}
    httpretty.register_uri(
        httpretty.GET,
        DOMAINS_URL,
        body=json.dumps(body),
        status=200,
        adding_headers={"Link": '<http://api.example.com/v2/x/?page=2>; rel="next"'},
    )

    with pytest.raises(ApiException):
        workspaces.list_domains("acme", credential=CREDENTIAL)

    assert len(httpretty.latest_requests()) == 1
