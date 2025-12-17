import httpretty
import pytest

from ..api.init import initialise_api
from ..rest import RestClient


class TestRestClient:
    @httpretty.activate(allow_net_connect=False, verbose=True)
    @pytest.mark.usefixtures("mock_keyring")
    def test_implicit_retry_for_status_codes(self):
        """Assert that the rest client retries certain status codes automatically."""
        # initialise_api() needs to be called before RestClient can be instantiated,
        # because it adds default attributes to cloudsmith_api.Configuration which
        # RestClient expects to be there.
        # In the context of a full test suite run, this will probably have already
        # happened elsewhere. But just in case this test is ever run in isolation...
        initialise_api()

        client = RestClient()

        method = "GET"
        url = "https://test.site"

        httpretty.register_uri(
            method,
            url,
            responses=[
                httpretty.Response("", status=500),
                httpretty.Response("", status=502),
                httpretty.Response("", status=503),
                httpretty.Response("", status=504),
                httpretty.Response("", status=500),
                httpretty.Response("", status=200),
            ],
        )

        r = client.request(method, url)

        assert len(httpretty.latest_requests()) == 6
        assert r.status == 200


@pytest.fixture
def mock_keyring(monkeypatch):
    """Mock keyring functions to prevent reading real SSO tokens from the system keyring.

    This is necessary because initialise_api() checks the keyring for SSO tokens,
    and if found, it attempts to refresh them via a network request. When running
    this test in isolation with httpretty mocking enabled, that network request
    will fail because it's not mocked.
    """
    # Import here to avoid circular imports
    import httpretty.core

    from .. import keyring

    # Mock all keyring getter functions to return None/False
    monkeypatch.setattr(keyring, "get_access_token", lambda api_host: None)
    monkeypatch.setattr(keyring, "get_refresh_token", lambda api_host: None)
    monkeypatch.setattr(keyring, "should_refresh_access_token", lambda api_host: False)

    # Patch httpretty's fake socket to handle shutdown() which urllib3 2.0+ calls
    # This fixes: "Failed to socket.shutdown because a real socket does not exist"
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )
