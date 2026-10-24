import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpretty
import pytest
import requests
from cloudsmith_api.rest import ApiException
from urllib3.exceptions import MaxRetryError, SSLError

from ..api.init import initialise_api
from ..rest import (
    NON_IDEMPOTENT_READ_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    RestClient,
)
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


@pytest.fixture
def silent_api():
    """Start an API server that reads each request and never replies."""
    requests_seen = []
    release = threading.Event()

    class SilentHandler(BaseHTTPRequestHandler):
        def _read_and_stall(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests_seen.append(self.command)
            release.wait()

        do_GET = do_POST = _read_and_stall

    server = ThreadingHTTPServer(("127.0.0.1", 0), SilentHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", requests_seen
    release.set()
    server.shutdown()
    server.server_close()


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

    @staticmethod
    def _sent_timeouts(monkeypatch, client):
        timeouts = []
        original_request = client.session.request

        def _record_timeout(*args, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return original_request(*args, **kwargs)

        monkeypatch.setattr(client.session, "request", _record_timeout)
        return timeouts

    @pytest.mark.parametrize(
        "method, expected_timeout",
        [
            ("GET", REQUEST_TIMEOUT_SECONDS),
            ("POST", (REQUEST_TIMEOUT_SECONDS, NON_IDEMPOTENT_READ_TIMEOUT_SECONDS)),
        ],
    )
    @httpretty.activate(allow_net_connect=False)
    def test_sets_a_default_timeout(self, monkeypatch, method, expected_timeout):
        """A stalled API does not block the CLI forever.

        A POST gets a longer read timeout, because the CLI does not retry it.
        """
        initialise_api()
        client = RestClient()
        httpretty.register_uri(method, "https://test.site", body="{}")
        timeouts = self._sent_timeouts(monkeypatch, client)

        client.request(method, "https://test.site")

        assert timeouts == [expected_timeout]

    @httpretty.activate(allow_net_connect=False)
    def test_keeps_an_explicit_timeout(self, monkeypatch):
        initialise_api()
        client = RestClient()
        httpretty.register_uri("GET", "https://test.site", body="{}")
        timeouts = self._sent_timeouts(monkeypatch, client)

        client.request("GET", "https://test.site", _request_timeout=(5, 120))

        assert timeouts == [(5, 120)]

    def test_rejects_an_invalid_timeout(self):
        initialise_api()
        client = RestClient()

        with pytest.raises(ApiException) as raised:
            client.request("GET", "https://test.site", _request_timeout=(5, 10, 15))

        assert raised.value.status == 0

    @pytest.mark.parametrize("method, expected_requests", [("POST", 1), ("GET", 3)])
    def test_retries_a_read_timeout_only_for_idempotent_methods(
        self, silent_api, method, expected_requests
    ):
        """A retry after a read timeout can repeat a POST that the server processed."""
        url, requests_seen = silent_api
        initialise_api()
        client = RestClient(retries=2, backoff_factor=0)

        with pytest.raises(ApiException):
            client.request(method, url, _request_timeout=(1, 0.2))

        assert len(requests_seen) == expected_requests

    @pytest.mark.parametrize(
        "method, status, expected_requests",
        [("POST", 504, 1), ("POST", 503, 3), ("GET", 504, 3)],
    )
    @httpretty.activate(allow_net_connect=False)
    def test_retries_a_gateway_error_only_for_idempotent_methods(
        self, method, status, expected_requests
    ):
        """A gateway error can replace the reply to a POST that the API processed."""
        initialise_api()
        client = RestClient(retries=2, backoff_factor=0)
        url = "https://test.site"
        httpretty.register_uri(method, url, status=status, body="")

        with pytest.raises(ApiException):
            client.request(method, url)

        assert len(httpretty.latest_requests()) == expected_requests


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

    def test_configured_proxy_beats_the_environment_proxy(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy.example.com:3128")
        session = create_requests_session(proxy="http://proxy.example.com:3128")
        settings = session.merge_environment_settings(
            "https://api.example.com/", {}, None, None, None
        )
        assert settings["proxies"]["https"] == "http://proxy.example.com:3128"


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
