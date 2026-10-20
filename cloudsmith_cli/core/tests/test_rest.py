import ssl

import httpretty
import pytest
import requests
from urllib3.exceptions import MaxRetryError, SSLError

from ..api.init import initialise_api
from ..rest import RestClient
from ..session import create_requests_session


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

        client = RestClient(backoff_factor=0)

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

    @httpretty.activate(allow_net_connect=False)
    def test_drops_the_api_key_on_a_redirect_to_another_host(self):
        """The v1 client, uploads and downloads keep the API key off other hosts."""
        api_url = "https://api.example.com/v1/things/"
        other_url = "https://other.example.com/things/"
        httpretty.register_uri(
            httpretty.GET, api_url, status=302, location=other_url, body=""
        )
        httpretty.register_uri(httpretty.GET, other_url, body="{}", status=200)

        session = create_requests_session()
        session.get(api_url, headers={"X-Api-Key": "test-api-key"}, timeout=5)

        assert "X-Api-Key" not in httpretty.last_request().headers

    @httpretty.activate(allow_net_connect=False)
    def test_keeps_the_api_key_on_a_redirect_to_the_same_host(self):
        """A redirect on the API host still gets the API key."""
        api_url = "https://api.example.com/v1/things"
        httpretty.register_uri(
            httpretty.GET, api_url, status=301, location=f"{api_url}/", body=""
        )
        httpretty.register_uri(httpretty.GET, f"{api_url}/", body="{}", status=200)

        session = create_requests_session()
        session.get(api_url, headers={"X-Api-Key": "test-api-key"}, timeout=5)

        assert httpretty.last_request().headers.get("X-Api-Key") == "test-api-key"


class TestSSLVerifyStrict:
    @staticmethod
    def _pool_kwargs(session, verify=True):
        request = requests.Request("GET", "https://api.example.com/").prepare()
        adapter = session.get_adapter(request.url)
        _, pool_kwargs = adapter.build_connection_pool_key_attributes(request, verify)
        return pool_kwargs

    def test_strict_by_default(self):
        session = create_requests_session()

        assert "ssl_context" not in self._pool_kwargs(session)

    def test_disabling_strict_clears_the_flag_but_still_verifies(self):
        session = create_requests_session(ssl_verify_strict=False)

        ctx = self._pool_kwargs(session)["ssl_context"]
        assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname

    def test_each_ca_bundle_gets_its_own_context(self):
        session = create_requests_session(ssl_verify_strict=False)

        first = self._pool_kwargs(session, verify="/ca/first.pem")["ssl_context"]
        second = self._pool_kwargs(session, verify="/ca/second.pem")["ssl_context"]
        assert first is not second
        assert (
            self._pool_kwargs(session, verify="/ca/first.pem")["ssl_context"] is first
        )

    def test_context_not_used_when_verification_disabled(self):
        session = create_requests_session(ssl_verify_strict=False)

        assert "ssl_context" not in self._pool_kwargs(session, verify=False)

    def test_falls_back_to_the_sdk_configuration(self):
        initialise_api(ssl_verify_strict=False)

        session = create_requests_session()

        assert "ssl_context" in self._pool_kwargs(session)


class TestRetryOnSSLErrors:
    def test_certificate_errors_are_not_retried(self):
        session = create_requests_session(retries=6)
        retry = session.get_adapter("https://api.example.com/").max_retries
        error = SSLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

        with pytest.raises(MaxRetryError) as raised:
            retry.increment("GET", "/", error=error)

        assert raised.value.reason is error
