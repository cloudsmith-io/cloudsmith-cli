"""Tests for the `cloudsmith credential-helper docker` command."""

import io
import json
from unittest.mock import patch

import httpretty
import httpretty.core
import pytest

from ....cli.commands.credential_helper.docker import docker
from ....core.credentials.models import CredentialResult
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import (
    CustomDomain,
    get_cache_path,
    get_custom_domains,
    get_format_domains,
    read_cache,
    write_cache,
)
from ....credential_helpers.docker.runtime import (
    execute,
    get_credentials as helper_get_credentials,
)

API_HOST = "https://api.cloudsmith.io"


class TestDockerRuntime:
    """Unit tests for the transport-light runtime (execute + get_credentials)."""

    # ------------------------------------------------------------------
    # execute – get operation
    # ------------------------------------------------------------------

    def test_execute_get_success_returns_json(self):
        """execute get → (0, json_string, None) when get_credentials returns a dict."""
        fake_creds = {"Username": "token", "Secret": "k_abc"}
        stdin = io.StringIO("docker.cloudsmith.io")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.return_value = fake_creds
            code, stdout, stderr = execute("get", stdin)

        assert code == 0
        assert json.loads(stdout) == fake_creds
        assert stderr is None

    def test_execute_get_refusal_returns_exit_1(self):
        """execute get → (1, None, refusal_msg) when get_credentials returns None."""
        stdin = io.StringIO("evil.example.com")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.return_value = None
            code, stdout, stderr = execute("get", stdin)

        assert code == 1
        assert stdout is None
        assert "Unable to retrieve credentials" in stderr

    def test_execute_get_empty_stdin_returns_exit_1(self):
        """execute get with empty stdin → (1, None, 'No server URL...')."""
        stdin = io.StringIO("")
        code, stdout, stderr = execute("get", stdin)

        assert code == 1
        assert stdout is None
        assert "No server URL provided" in stderr

    def test_execute_get_exception_is_caught_at_boundary(self):
        """D17: a network/SDK error inside get_credentials must NOT escape execute.

        The protocol boundary degrades to a clean refusal (exit 1) so that
        docker pull/push never sees a Python traceback.
        """
        stdin = io.StringIO("docker.cloudsmith.io")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.side_effect = RuntimeError("boom")
            code, stdout, stderr = execute("get", stdin)

        assert code == 1
        assert stdout is None
        assert "Unable to retrieve credentials" in stderr

    def test_execute_get_broken_pipe_stdin_is_caught_at_boundary(self):
        """A broken-pipe OSError from stdin.read() must not escape execute.

        The widened boundary covers the stdin read, so a broken pipe degrades
        to a clean refusal (exit 1) rather than propagating an exception.
        """
        from ....credential_helpers.docker.runtime import _REFUSAL_MESSAGE

        class BrokenPipeStdin:
            def read(self):
                raise OSError("broken pipe")

        credential = CredentialResult(api_key="k_abc", source_name="test")
        code, stdout, stderr = execute(
            "get", BrokenPipeStdin(), credential=credential, api_host=None
        )

        assert code == 1
        assert stdout is None
        assert stderr == _REFUSAL_MESSAGE

    # ------------------------------------------------------------------
    # execute – write/no-op operations
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("operation", ["store", "erase"])
    def test_execute_store_erase_returns_0_no_output(self, operation):
        """store and erase drain stdin and return (0, None, None)."""
        stdin = io.StringIO('{"ServerURL": "docker.cloudsmith.io"}')
        code, stdout, stderr = execute(operation, stdin)

        assert code == 0
        assert stdout is None
        assert stderr is None

    def test_execute_list_returns_empty_json_object(self):
        """list always returns (0, '{}', None)."""
        stdin = io.StringIO("")
        code, stdout, stderr = execute("list", stdin)

        assert code == 0
        assert stdout == "{}"
        assert stderr is None

    def test_execute_unknown_operation_returns_exit_1(self):
        """An unrecognised operation name returns (1, None, error_message)."""
        stdin = io.StringIO("")
        code, stdout, stderr = execute("frobnicate", stdin)

        assert code == 1
        assert stdout is None
        assert "Unknown operation" in stderr
        assert "frobnicate" in stderr

    # ------------------------------------------------------------------
    # get_credentials
    # ------------------------------------------------------------------

    def test_get_credentials_returns_dict_for_cloudsmith_domain(self):
        """get_credentials returns username+secret for a Cloudsmith domain."""
        credential = CredentialResult(api_key="k_xyz", source_name="test")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.is_cloudsmith_domain"
        ) as mock_is:
            mock_is.return_value = True
            result = helper_get_credentials(
                "docker.cloudsmith.io", credential=credential
            )

        assert result == {"Username": "token", "Secret": "k_xyz"}

    def test_get_credentials_returns_none_when_no_credential(self):
        """get_credentials returns None when credential is absent."""
        result = helper_get_credentials("docker.cloudsmith.io", credential=None)
        assert result is None

    def test_get_credentials_returns_none_for_non_cloudsmith_domain(self):
        """get_credentials returns None when is_cloudsmith_domain is False."""
        credential = CredentialResult(api_key="k_xyz", source_name="test")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.is_cloudsmith_domain"
        ) as mock_is:
            mock_is.return_value = False
            result = helper_get_credentials("evil.example.com", credential=credential)

        assert result is None


class TestDockerCredentialHelper:
    """Test suite for the Docker credential helper CLI command."""

    def test_get_credentials_for_cloudsmith_io(self, runner):
        """`*.cloudsmith.io` URLs should return credentials JSON on stdout."""
        fake_creds = {"Username": "token", "Secret": "k_abc"}

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.return_value = fake_creds
            result = runner.invoke(
                docker,
                args=["get"],
                input="docker.cloudsmith.io",
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert json.dumps(fake_creds) in result.stdout
        mock_get.assert_called_once()
        called_args, _called_kwargs = mock_get.call_args
        assert called_args[0] == "docker.cloudsmith.io"

    def test_no_arg_defaults_to_get(self, runner):
        """Invoking docker with no OPERATION argument defaults to 'get'."""
        fake_creds = {"Username": "token", "Secret": "k_abc"}

        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.return_value = fake_creds
            result = runner.invoke(
                docker,
                args=[],
                input="docker.cloudsmith.io",
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert json.dumps(fake_creds) in result.stdout

    def test_refuses_non_cloudsmith_domain(self, runner):
        """Non-Cloudsmith URLs should exit 1 with an error message on stderr."""
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            mock_get.return_value = None
            result = runner.invoke(
                docker,
                args=["get"],
                input="evil.example.com",
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "Unable to retrieve credentials" in result.output
        mock_get.assert_called_once()

    def test_empty_stdin_exits_1(self, runner):
        """Empty stdin should exit 1 with a descriptive error on stderr."""
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials"
        ) as mock_get:
            result = runner.invoke(
                docker, args=["get"], input="", catch_exceptions=False
            )

        assert result.exit_code == 1
        assert "No server URL provided" in result.output
        mock_get.assert_not_called()

    @pytest.mark.parametrize("operation", ["store", "erase"])
    def test_store_erase_exit_0_no_output(self, runner, operation):
        """store and erase exit 0 and produce no output."""
        result = runner.invoke(
            docker,
            args=[operation],
            input='{"ServerURL": "docker.cloudsmith.io"}',
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_list_prints_empty_json(self, runner):
        """list exits 0 and prints '{}'."""
        result = runner.invoke(docker, args=["list"], input="", catch_exceptions=False)

        assert result.exit_code == 0
        assert "{}" in result.output

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
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com", backend_kind=6, enabled=True, validated=True
                )
            ],
        )

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


class TestBackendKind:
    """Spot-check BackendKind enum values."""

    def test_docker_is_6(self):
        assert BackendKind.DOCKER == 6

    def test_npm_is_9(self):
        assert BackendKind.NPM == 9

    def test_deb_is_0(self):
        assert BackendKind.DEB == 0

    def test_default_is_99(self):
        assert BackendKind.DEFAULT == 99


class TestGetCustomDomains:
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
    def test_success_builds_records_and_caches(self):
        """A 200 response builds CustomDomain records and caches them."""
        body = [
            {
                "host": "docker.acme.com",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": True,
                "validated": True,
            },
            {
                "host": "dl.acme.com",
                "backend_kind": None,
                "domain_type": 0,
                "enabled": True,
                "validated": True,
            },
            {
                "host": "",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": True,
                "validated": True,
            },  # blank host is skipped
        ]
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        domains = get_custom_domains("acme", api_key="k_abc", api_host=API_HOST)

        assert len(domains) == 2
        assert domains[0] == CustomDomain(
            host="docker.acme.com", backend_kind=6, enabled=True, validated=True
        )
        assert domains[1] == CustomDomain(
            host="dl.acme.com", backend_kind=None, enabled=True, validated=True
        )
        # Auth header proves the SDK auth path is exercised (X-Api-Key, not Bearer).
        assert httpretty.last_request().headers.get("X-Api-Key") == "k_abc"

    @httpretty.activate(allow_net_connect=False)
    def test_cache_round_trip(self):
        """Fetched records are cached; a second call returns the same records from cache."""
        body = [
            {
                "host": "docker.acme.com",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": True,
                "validated": True,
            },
        ]
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        first = get_custom_domains("acme", api_key="k_abc", api_host=API_HOST)

        # Verify the cache contains structured records.
        cached = read_cache(get_cache_path("acme"))
        assert cached is not None
        assert cached == first
        assert cached[0].backend_kind == 6
        assert cached[0].enabled is True
        assert cached[0].validated is True

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

        get_custom_domains(
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

        assert get_custom_domains("acme", api_key="k", api_host=API_HOST) == []
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

        assert get_custom_domains("acme", api_key="k", api_host=API_HOST) == []
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

        assert get_custom_domains("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) is None

    @httpretty.activate(allow_net_connect=False)
    def test_server_error_returns_empty_without_caching(self):
        """A 500 returns [] without raising and without caching."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Boom."}),
            status=500,
            content_type="application/json",
        )

        assert get_custom_domains("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) is None

    @httpretty.activate(allow_net_connect=False)
    def test_401_does_not_cache(self):
        """A 401 returns [] but does NOT cache (may succeed later once authed)."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps({"detail": "Unauthorized."}),
            status=401,
            content_type="application/json",
        )

        assert get_custom_domains("acme", api_key="k", api_host=API_HOST) == []
        assert read_cache(get_cache_path("acme")) is None

    def test_legacy_string_cache_is_a_miss(self, tmp_path):
        """A cache file with a string-list 'domains' (old format) returns None."""
        import time

        cache_path = get_cache_path("acme")
        legacy_data = {
            "domains": ["docker.acme.com"],
            "cached_at": time.time(),
        }
        cache_path.write_text(json.dumps(legacy_data), encoding="utf-8")
        assert read_cache(cache_path) is None

    def test_empty_domains_cache_is_a_hit(self, tmp_path):
        """A cache file with 'domains': [] returns [] (valid cached 'no domains')."""
        import time

        cache_path = get_cache_path("acme")
        empty_data = {
            "domains": [],
            "cached_at": time.time(),
        }
        cache_path.write_text(json.dumps(empty_data), encoding="utf-8")
        assert read_cache(cache_path) == []


class TestGetFormatDomains:
    """Test get_format_domains filters by backend_kind, enabled, and validated."""

    @pytest.fixture(autouse=True)
    def _cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
            lambda: str(tmp_path),
        )
        monkeypatch.setattr(
            httpretty.core.fakesock.socket,
            "shutdown",
            lambda self, how: None,
            raising=False,
        )

    @httpretty.activate(allow_net_connect=False)
    def test_returns_only_enabled_validated_docker_hosts(self):
        """Only Docker domains that are both enabled and validated are returned."""
        body = [
            # Should be included: Docker, enabled, validated
            {
                "host": "docker.acme.com",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": True,
                "validated": True,
            },
            # Excluded: different backend_kind (NPM = 9)
            {
                "host": "npm.acme.com",
                "backend_kind": 9,
                "domain_type": 1,
                "enabled": True,
                "validated": True,
            },
            # Excluded: Docker but not enabled
            {
                "host": "docker2.acme.com",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": False,
                "validated": True,
            },
            # Excluded: Docker but not validated
            {
                "host": "docker3.acme.com",
                "backend_kind": 6,
                "domain_type": 1,
                "enabled": True,
                "validated": False,
            },
            # Excluded: backend_kind is None (download domain)
            {
                "host": "dl.acme.com",
                "backend_kind": None,
                "domain_type": 0,
                "enabled": True,
                "validated": True,
            },
        ]
        httpretty.register_uri(
            httpretty.GET,
            f"{API_HOST}/orgs/acme/custom-domains/",
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        hosts = get_format_domains(
            "acme", BackendKind.DOCKER, api_key="k", api_host=API_HOST
        )

        assert hosts == ["docker.acme.com"]


class TestIsCloudsmithDomain:
    """Test is_cloudsmith_domain with standard and custom domains."""

    @pytest.fixture(autouse=True)
    def _cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
            lambda: str(tmp_path),
        )

    def test_standard_cloudsmith_io_true(self):
        """Standard *.cloudsmith.io domains are true without any API call."""
        from ....credential_helpers.common import is_cloudsmith_domain

        assert is_cloudsmith_domain("docker.cloudsmith.io") is True
        assert is_cloudsmith_domain("dl.cloudsmith.io") is True

    def test_standard_cloudsmith_com_true(self):
        """Standard *.cloudsmith.com domains are true without any API call."""
        from ....credential_helpers.common import is_cloudsmith_domain

        assert is_cloudsmith_domain("docker.cloudsmith.com") is True

    def test_non_cloudsmith_false(self):
        """Unrelated hostnames return False."""
        from ....credential_helpers.common import is_cloudsmith_domain

        assert is_cloudsmith_domain("evil.example.com") is False

    def test_custom_enabled_validated_host_true(self, tmp_path, monkeypatch):
        """An enabled+validated custom domain in cache returns True."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        assert (
            is_cloudsmith_domain(
                "docker.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
            )
            is True
        )

    def test_custom_disabled_host_false(self, tmp_path, monkeypatch):
        """A disabled custom domain is not treated as a Cloudsmith domain."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=False,
                    validated=True,
                )
            ],
        )

        assert (
            is_cloudsmith_domain(
                "docker.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
            )
            is False
        )

    def test_custom_enabled_not_validated_host_false(self, tmp_path, monkeypatch):
        """An enabled but unvalidated custom domain is not a Cloudsmith domain."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=True,
                    validated=False,
                )
            ],
        )

        assert (
            is_cloudsmith_domain(
                "docker.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
            )
            is False
        )

    # ------------------------------------------------------------------
    # backend_kind filtering
    # ------------------------------------------------------------------

    def test_backend_kind_docker_matches_docker_custom_domain(
        self, tmp_path, monkeypatch
    ):
        """With backend_kind=DOCKER, a Docker custom domain (kind=6) returns True."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        assert (
            is_cloudsmith_domain(
                "docker.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
                backend_kind=BackendKind.DOCKER,
            )
            is True
        )

    def test_backend_kind_docker_rejects_npm_custom_domain(self, tmp_path, monkeypatch):
        """With backend_kind=DOCKER, an NPM custom domain (kind=9) returns False."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="npm.acme.com",
                    backend_kind=9,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        assert (
            is_cloudsmith_domain(
                "npm.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
                backend_kind=BackendKind.DOCKER,
            )
            is False
        )

    def test_backend_kind_docker_standard_domain_always_true(self):
        """Standard *.cloudsmith.io is True even when backend_kind=DOCKER (no API call)."""
        from ....credential_helpers.common import is_cloudsmith_domain

        assert (
            is_cloudsmith_domain(
                "docker.cloudsmith.io",
                backend_kind=BackendKind.DOCKER,
            )
            is True
        )
        assert (
            is_cloudsmith_domain(
                "something.cloudsmith.io",
                backend_kind=BackendKind.DOCKER,
            )
            is True
        )

    def test_backend_kind_none_default_matches_any_format(self, tmp_path, monkeypatch):
        """backend_kind=None (default) accepts any enabled+validated custom domain."""
        from ....credential_helpers.common import is_cloudsmith_domain

        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="npm.acme.com",
                    backend_kind=9,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        # Default (no backend_kind) still returns True for any format
        assert (
            is_cloudsmith_domain(
                "npm.acme.com",
                api_key="k_abc",
                api_host=API_HOST,
            )
            is True
        )


class TestDockerRuntimeBackendKindFiltering:
    """Tests that the Docker runtime refuses non-Docker custom domains."""

    @pytest.fixture(autouse=True)
    def _cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
            lambda: str(tmp_path),
        )
        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    def test_get_credentials_refuses_npm_custom_domain(self, tmp_path):
        """get_credentials returns None for an NPM custom domain (not a Docker registry)."""
        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="npm.acme.com",
                    backend_kind=9,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        credential = CredentialResult(api_key="k_xyz", source_name="test")
        result = helper_get_credentials(
            "npm.acme.com",
            credential=credential,
            api_host=API_HOST,
        )

        assert result is None

    def test_get_credentials_serves_docker_custom_domain(self, tmp_path):
        """get_credentials returns creds for a Docker custom domain (backend_kind=6)."""
        cache_path = get_cache_path("acme")
        write_cache(
            cache_path,
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=True,
                    validated=True,
                )
            ],
        )

        credential = CredentialResult(api_key="k_xyz", source_name="test")
        result = helper_get_credentials(
            "docker.acme.com",
            credential=credential,
            api_host=API_HOST,
        )

        assert result == {"Username": "token", "Secret": "k_xyz"}
