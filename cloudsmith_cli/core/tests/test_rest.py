import datetime
import http.server
import ipaddress
import socket
import ssl
import threading

import httpretty
import pytest
import requests
import truststore
from cloudsmith_api.rest import ApiException
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from urllib3.exceptions import MaxRetryError, NameResolutionError, ProxyError, SSLError
from urllib3.util.ssl_ import create_urllib3_context

from ..api.init import initialise_api
from ..rest import READ_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS, RestClient
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
            ("GET", (REQUEST_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)),
            ("POST", (REQUEST_TIMEOUT_SECONDS, None)),
        ],
    )
    @httpretty.activate(allow_net_connect=False)
    def test_sets_a_default_timeout(self, monkeypatch, method, expected_timeout):
        """A stalled API does not block the CLI forever.

        A POST gets no read timeout, because the retry after a read timeout
        sends the POST again and can create a second entry.
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


class TestSSLSystemTrustStore:
    _pool_kwargs = staticmethod(TestSSLVerifyStrict._pool_kwargs)

    def test_uses_the_system_trust_store(self):
        session = create_requests_session(ssl_system_trust_store=True)

        ctx = self._pool_kwargs(session)["ssl_context"]
        assert isinstance(ctx, truststore.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname
        assert ctx.verify_flags == create_urllib3_context().verify_flags

    def test_without_strict_clears_the_strict_flag(self):
        session = create_requests_session(
            ssl_system_trust_store=True, ssl_verify_strict=False
        )

        ctx = self._pool_kwargs(session)["ssl_context"]
        assert isinstance(ctx, truststore.SSLContext)
        assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT

    def test_context_not_used_when_verification_disabled(self):
        session = create_requests_session(ssl_system_trust_store=True)

        assert "ssl_context" not in self._pool_kwargs(session, verify=False)

    def test_falls_back_to_the_sdk_configuration(self):
        initialise_api(ssl_system_trust_store=True)

        session = create_requests_session()

        assert isinstance(
            self._pool_kwargs(session)["ssl_context"], truststore.SSLContext
        )

    def test_trusts_the_ca_bundle_in_addition(self, tls_server):
        url, ca_bundle = tls_server
        session = create_requests_session(ssl_system_trust_store=True, retries=0)

        assert session.get(url, verify=ca_bundle, timeout=10).status_code == 200

    def test_rejects_a_ca_that_no_store_trusts(self, tls_server):
        url, _ = tls_server
        session = create_requests_session(ssl_system_trust_store=True, retries=0)

        with pytest.raises(requests.exceptions.SSLError):
            session.get(url, timeout=10)


def _certificate(subject, issuer, public_key, signing_key, extensions):
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
    )
    for extension, critical in extensions:
        builder = builder.add_extension(extension, critical=critical)
    return builder.sign(signing_key, hashes.SHA256())


def _write_tls_files(directory):
    """Write a test CA bundle and a server certificate chain for 127.0.0.1."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CLI Test CA")])
    ca_cert = _certificate(
        ca_name,
        ca_name,
        ca_key.public_key(),
        ca_key,
        [
            (x509.BasicConstraints(ca=True, path_length=None), True),
            (
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                True,
            ),
            (x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False),
        ],
    )
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = _certificate(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]),
        ca_name,
        server_key.public_key(),
        ca_key,
        [
            (x509.BasicConstraints(ca=False, path_length=None), True),
            (
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                False,
            ),
            (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False),
            (
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                False,
            ),
        ],
    )
    ca_bundle = directory / "ca.pem"
    ca_bundle.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    chain = directory / "server.pem"
    chain.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + server_cert.public_bytes(serialization.Encoding.PEM)
    )
    return ca_bundle, chain


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _QuietHTTPServer(http.server.HTTPServer):
    def handle_error(self, request, client_address):
        pass


@pytest.fixture
def tls_server(tmp_path):
    """Serve HTTPS on 127.0.0.1 with a certificate from a test CA."""
    ca_bundle, chain = _write_tls_files(tmp_path)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(chain)
    server = _QuietHTTPServer(("127.0.0.1", 0), _OkHandler)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_port}/", str(ca_bundle)
    server.shutdown()
    server.server_close()


@pytest.fixture
def retry():
    session = create_requests_session(retries=6)
    return session.get_adapter("https://api.example.com/").max_retries


class TestRetryOnSSLErrors:
    def test_certificate_errors_are_not_retried(self, retry):
        error = SSLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

        with pytest.raises(MaxRetryError) as raised:
            retry.increment("GET", "/", error=error)

        assert raised.value.reason is error


def name_resolution_error(reason):
    """Return the ``NameResolutionError`` that urllib3 raises from ``reason``."""
    error = NameResolutionError("api.example.com", None, reason)
    error.__cause__ = reason
    return error


class TestRetryOnNameResolutionErrors:
    @pytest.mark.parametrize("errno", [socket.EAI_NONAME, 11001])
    def test_unknown_hosts_are_not_retried(self, retry, errno):
        error = name_resolution_error(socket.gaierror(errno, "not known"))

        with pytest.raises(MaxRetryError) as raised:
            retry.increment("GET", "/", error=error)

        assert raised.value.reason is error

    def test_unknown_proxy_hosts_are_not_retried(self, retry):
        reason = name_resolution_error(socket.gaierror(socket.EAI_NONAME, "not known"))
        error = ProxyError("Unable to connect to proxy", reason)
        error.__cause__ = reason

        with pytest.raises(MaxRetryError) as raised:
            retry.increment("GET", "/", error=error)

        assert raised.value.reason is error

    @pytest.mark.parametrize(
        "error",
        [
            name_resolution_error(socket.gaierror(socket.EAI_AGAIN, "try again")),
            NameResolutionError("api.example.com", None, None),
        ],
        ids=["temporary-failure", "no-gaierror"],
    )
    def test_other_name_resolution_errors_are_retried(self, retry, error):
        assert retry.increment("GET", "/", error=error).total == 5
