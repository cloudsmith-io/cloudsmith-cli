import httpretty
import pytest

from ..api.init import initialise_api
from ..rest import RestClient, create_requests_session


@pytest.fixture(autouse=True)
def patch_httpretty_socket(monkeypatch):
    """Patch httpretty's fake socket to handle shutdown() which urllib3 2.0+ calls."""
    import httpretty.core

    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )


class TestRestClient:
    @httpretty.activate(allow_net_connect=False, verbose=True)
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


class TestCreateRequestsSession:
    @pytest.fixture(autouse=True)
    def setup(self):
        initialise_api()

    def test_sets_user_agent_header(self):
        session = create_requests_session(user_agent="test-agent/1.0")
        assert session.headers["User-Agent"] == "test-agent/1.0"

    def test_sets_extra_headers(self):
        session = create_requests_session(headers={"X-Custom": "value"})
        assert session.headers["X-Custom"] == "value"
