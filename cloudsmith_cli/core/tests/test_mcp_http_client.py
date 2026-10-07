"""Tests for the MCP server's HTTP client TLS/proxy configuration.

Regression coverage for the v1.28.0 release failure: mcp>=2 switched to httpx2,
whose default TLS context reads the OS trust store via OpenSSL's compiled-in
paths. In the frozen glibc binaries those paths don't exist on Debian hosts, so
every MCP HTTPS call failed with CERTIFICATE_VERIFY_FAILED.
"""

import ssl
from unittest.mock import patch

import certifi
import cloudsmith_api
import httpx2
import pytest

from cloudsmith_cli.core.mcp import server
from cloudsmith_cli.core.mcp.server import (
    CA_BUNDLE_ENV_VARS,
    DynamicMCPServer,
    create_http_client,
    create_ssl_context,
)


@pytest.fixture(autouse=True)
def clear_ca_env(monkeypatch):
    for name in CA_BUNDLE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api_config():
    config = cloudsmith_api.Configuration()
    config.host = "https://api.cloudsmith.io"
    config.verify_ssl = True
    config.ssl_ca_cert = None
    config.cert_file = None
    config.key_file = None
    config.proxy = None
    return config


def _spy_create_default_context():
    return patch.object(
        server.ssl, "create_default_context", wraps=ssl.create_default_context
    )


class TestCreateSSLContext:
    def test_defaults_to_certifi_bundle_not_os_trust_store(self, api_config):
        with _spy_create_default_context() as spy:
            ctx = create_ssl_context(api_config)

        spy.assert_called_once_with(cafile=certifi.where())
        assert type(ctx) is ssl.SSLContext
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname
        assert ctx.cert_store_stats()["x509_ca"] > 0

    def test_configured_ssl_ca_cert_takes_precedence(self, api_config, monkeypatch):
        api_config.ssl_ca_cert = certifi.where()
        monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/env-bundle.pem")

        with _spy_create_default_context() as spy:
            create_ssl_context(api_config)

        spy.assert_called_once_with(cafile=certifi.where())

    @pytest.mark.parametrize("env_var", ["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"])
    def test_ca_bundle_env_var_is_honoured(self, api_config, monkeypatch, env_var):
        monkeypatch.setenv(env_var, certifi.where())

        with (
            _spy_create_default_context() as spy,
            patch.object(server.certifi, "where") as where,
        ):
            create_ssl_context(api_config)

        spy.assert_called_once_with(cafile=certifi.where())
        where.assert_not_called()

    def test_ca_directory_uses_capath(self, api_config, monkeypatch, tmp_path):
        monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))

        with _spy_create_default_context() as spy:
            create_ssl_context(api_config)

        spy.assert_called_once_with(capath=str(tmp_path))

    def test_verification_disabled(self, api_config):
        api_config.verify_ssl = False

        assert create_ssl_context(api_config) is False

    def test_client_certificate_is_loaded(self, api_config):
        api_config.cert_file = "/path/client.pem"
        api_config.key_file = "/path/client.key"

        with patch.object(ssl.SSLContext, "load_cert_chain") as load_cert_chain:
            create_ssl_context(api_config)

        load_cert_chain.assert_called_once_with("/path/client.pem", "/path/client.key")


class TestCreateHttpClient:
    def test_passes_tls_context_proxy_and_mcp_default_timeouts(self, api_config):
        api_config.proxy = "http://proxy.example:3128"
        ctx = ssl.create_default_context()

        with patch.object(server.httpx2, "AsyncClient") as client_cls:
            create_http_client(api_config, headers={"X-Api-Key": "k"}, verify=ctx)

        kwargs = client_cls.call_args.kwargs
        assert kwargs["verify"] is ctx
        assert kwargs["proxy"] == "http://proxy.example:3128"
        assert kwargs["headers"] == {"X-Api-Key": "k"}
        assert kwargs["timeout"] == httpx2.Timeout(30.0, read=300.0)

    def test_no_proxy_kwarg_when_unset(self, api_config):
        with patch.object(server.httpx2, "AsyncClient") as client_cls:
            create_http_client(api_config)

        assert "proxy" not in client_cls.call_args.kwargs
        assert isinstance(client_cls.call_args.kwargs["verify"], ssl.SSLContext)


class TestDynamicMCPServerHttpClient:
    def test_reuses_one_tls_context_per_server(self, api_config):
        mcp_server = DynamicMCPServer(api_config=api_config)

        with (
            patch.object(
                server, "create_ssl_context", wraps=create_ssl_context
            ) as build_ctx,
            patch.object(server.httpx2, "AsyncClient") as client_cls,
        ):
            mcp_server._create_http_client()
            mcp_server._create_http_client(headers={"Accept": "application/json"})

        build_ctx.assert_called_once_with(api_config)
        first, second = client_cls.call_args_list
        assert first.kwargs["verify"] is second.kwargs["verify"]
