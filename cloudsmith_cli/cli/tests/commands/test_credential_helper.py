"""Tests for the `cloudsmith credential-helper docker` command."""

import io
import json
from unittest.mock import patch

import httpretty
import httpretty.core
import pytest

from ....cli.commands.credential_helper.docker import docker
from ....core.credentials.models import CredentialResult
from ....credential_helpers.custom_domains import (
    get_cache_path,
    get_custom_domains_for_org,
    read_cache,
    write_cache,
)
from ....credential_helpers.docker.credentials import (
    get_credentials as helper_get_credentials,
)
from ....credential_helpers.docker.wrapper import main as docker_wrapper_main

API_HOST = "https://api.cloudsmith.io"


class TestDockerCredentialHelper:
    """Test suite for the Docker credential helper CLI command."""

    def test_get_credentials_for_cloudsmith_io(self, runner):
        """`*.cloudsmith.io` URLs should return credentials JSON on stdout."""
        fake_creds = {"Username": "token", "Secret": "k_abc"}

        with patch(
            "cloudsmith_cli.cli.commands.credential_helper.docker.get_credentials"
        ) as mock_get:
            mock_get.return_value = fake_creds
            result = runner.invoke(
                docker, input="docker.cloudsmith.io", catch_exceptions=False
            )

        assert result.exit_code == 0
        # stdout should contain the serialized JSON exactly as produced by the command.
        assert json.dumps(fake_creds) in result.stdout
        mock_get.assert_called_once()
        # The first positional argument to get_credentials is the server URL.
        called_args, _called_kwargs = mock_get.call_args
        assert called_args[0] == "docker.cloudsmith.io"

    def test_refuses_non_cloudsmith_domain(self, runner):
        """Non-Cloudsmith URLs should exit 1 with an error message on stderr."""
        with patch(
            "cloudsmith_cli.cli.commands.credential_helper.docker.get_credentials"
        ) as mock_get:
            mock_get.return_value = None
            result = runner.invoke(
                docker, input="evil.example.com", catch_exceptions=False
            )

        assert result.exit_code == 1
        assert "Unable to retrieve credentials" in result.output
        mock_get.assert_called_once()

    def test_empty_stdin_exits_1(self, runner):
        """Empty stdin should exit 1 with a descriptive error on stderr."""
        with patch(
            "cloudsmith_cli.cli.commands.credential_helper.docker.get_credentials"
        ) as mock_get:
            result = runner.invoke(docker, input="", catch_exceptions=False)

        assert result.exit_code == 1
        assert "No server URL provided" in result.output
        # get_credentials should never be called when there is no URL.
        mock_get.assert_not_called()

    def test_custom_domain_with_cached_response(self, tmp_path, monkeypatch):
        """A cached custom-domain entry should authorise credential issuance.

        This exercises the helper-level `get_credentials` (not the click command)
        so the on-disk custom-domain cache lookup runs end to end. The click
        command's wiring is covered by the other tests in this class.
        """
        # Point the cache base at a per-test temp directory.
        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
            lambda: str(tmp_path),
        )
        # is_cloudsmith_domain reads CLOUDSMITH_ORG from the environment.
        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

        # Seed the cache file at the path the helper will read from.
        cache_path = get_cache_path("acme")
        assert cache_path.parent.exists(), "get_cache_path should create the dir"
        write_cache(cache_path, ["docker.acme.com"])

        credential = CredentialResult(api_key="k_xyz", source_name="test")

        # A cache hit must short-circuit before any SDK call.
        def _boom(*_args, **_kwargs):
            raise AssertionError(
                "API call attempted despite a valid custom-domain cache"
            )

        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.list_custom_domains",
            _boom,
        )

        result = helper_get_credentials(
            "docker.acme.com",
            credential=credential,
            api_host="https://api.cloudsmith.io",
        )

        assert result == {"Username": "token", "Secret": "k_xyz"}

    @pytest.mark.parametrize("operation", ["store", "erase"])
    def test_wrapper_read_only_operations_are_noops(
        self, operation, monkeypatch, capsys
    ):
        """Docker's write operations should succeed without storing anything."""
        monkeypatch.setattr("sys.argv", ["docker-credential-cloudsmith", operation])
        monkeypatch.setattr("sys.stdin", io.StringIO('{"ServerURL":"example.com"}'))

        with pytest.raises(SystemExit) as exc:
            docker_wrapper_main()

        assert exc.value.code == 0
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == ""

    def test_wrapper_list_returns_empty_json(self, monkeypatch, capsys):
        """Docker's list operation should return an empty credential object."""
        monkeypatch.setattr("sys.argv", ["docker-credential-cloudsmith", "list"])

        with pytest.raises(SystemExit) as exc:
            docker_wrapper_main()

        assert exc.value.code == 0
        output = capsys.readouterr()
        assert output.out == "{}\n"
        assert output.err == ""


class TestGetCustomDomainsForOrg:
    """Exercise the SDK-backed custom-domains fetch path.

    These tests stub the v1 `GET /orgs/{org}/custom-domains/` endpoint that the
    `cloudsmith_api` SDK calls. The on-disk cache base is redirected to a temp dir
    per test.
    """

    @pytest.fixture(autouse=True)
    def _cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
            lambda: str(tmp_path),
        )
        # httpretty's fake socket has no shutdown(); urllib3 calls it during
        # getresponse(). Stub it so requests succeed under httpretty.
        monkeypatch.setattr(
            httpretty.core.fakesock.socket,
            "shutdown",
            lambda self, how: None,
            raising=False,
        )

    @httpretty.activate(allow_net_connect=False)
    def test_success_extracts_hosts_and_caches(self):
        """A 200 response yields the `.host` of each model and caches the result."""
        body = [
            {"host": "docker.acme.com", "slug_perm": "a"},
            {"host": "dl.acme.com", "slug_perm": "b"},
            {"host": "", "slug_perm": "c"},  # blank host is skipped
        ]
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        domains = get_custom_domains_for_org("acme", api_key="k_abc", api_host=API_HOST)

        assert domains == ["docker.acme.com", "dl.acme.com"]
        # Auth header proves the SDK auth path is exercised (X-Api-Key, not Bearer).
        assert httpretty.last_request().headers.get("X-Api-Key") == "k_abc"
        # Result is cached.
        assert read_cache(get_cache_path("acme")) == ["docker.acme.com", "dl.acme.com"]

    @httpretty.activate(allow_net_connect=False)
    def test_bearer_auth_uses_authorization_header(self):
        """A bearer credential sends an Authorization: Bearer header."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps([]),
            status=200,
            content_type="application/json",
        )

        get_custom_domains_for_org(
            "acme", api_key="tok123", auth_type="bearer", api_host=API_HOST
        )

        assert httpretty.last_request().headers.get("Authorization") == "Bearer tok123"

    @httpretty.activate(allow_net_connect=False)
    def test_404_caches_empty(self):
        """A 404 returns [] and caches the empty result to avoid repeat lookups."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        assert get_custom_domains_for_org("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) == []

    @httpretty.activate(allow_net_connect=False)
    def test_402_caches_empty(self):
        """A 402 (feature not enabled) returns [] and caches the empty result."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Upgrade required."}),
            status=402,
            content_type="application/json",
        )

        assert get_custom_domains_for_org("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) == []

    @httpretty.activate(allow_net_connect=False)
    def test_403_does_not_cache(self):
        """A 403 returns [] but does NOT cache (may succeed later once authed)."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Forbidden."}),
            status=403,
            content_type="application/json",
        )

        assert get_custom_domains_for_org("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) is None

    @httpretty.activate(allow_net_connect=False)
    def test_server_error_returns_empty_without_raising(self):
        """A 500 returns [] without raising and without caching."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Boom."}),
            status=500,
            content_type="application/json",
        )

        assert get_custom_domains_for_org("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) is None
