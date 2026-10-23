"""Tests for the `cloudsmith credential-helper docker` command."""

import io
import json
import time
from unittest.mock import patch

import httpretty
import httpretty.core
import pytest

from ....cli.commands.credential_helper.docker import docker
from ....core.api.exceptions import ApiException
from ....core.api.init import initialise_api
from ....core.credentials.models import CredentialResult
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.common import (
    REFUSAL_MESSAGE,
    is_cloudsmith_domain,
    is_standard_cloudsmith_domain,
)
from ....credential_helpers.domains import (
    CACHE_FORMAT_VERSION,
    get_cache_path,
    get_format_domains,
    get_workspace_domains,
    read_all_cached_domains,
    read_cache,
    write_cache,
)
from ....credential_helpers.docker.runtime import (
    execute,
)
from ....credential_helpers.docker.runtime import (
    get_credentials as helper_get_credentials,
)

API_HOST = "https://api.cloudsmith.io"


def _server_domain(name, domain_type, scope="WORKSPACE"):
    """Build one entry of the v2 Workspace domains listing."""
    return {
        "domain_name": name,
        "domain_type": domain_type,
        "domain_scope": scope,
        "repository": None,
    }


# ---------------------------------------------------------------------------
# 1. runtime.execute — protocol matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation,get_return,stdin_text,expected_code,expected_stdout,stderr_substr",
    [
        # get-success: get_credentials returns a dict → (0, json, None)
        (
            "get",
            {"Username": "token", "Secret": "k_abc"},
            "docker.cloudsmith.io",
            0,
            json.dumps({"Username": "token", "Secret": "k_abc"}),
            None,
        ),
        # get-refusal: get_credentials returns None → (1, not-found, refusal)
        (
            "get",
            None,
            "evil.example.com",
            1,
            "credentials not found in native keychain",
            "Unable to retrieve credentials",
        ),
        # store: drains stdin, returns (0, None, None)
        ("store", None, '{"ServerURL": "docker.cloudsmith.io"}', 0, None, None),
        # erase: drains stdin, returns (0, None, None)
        ("erase", None, '{"ServerURL": "docker.cloudsmith.io"}', 0, None, None),
        # list: returns (0, '{}', None)
        ("list", None, "", 0, "{}", None),
        # unknown: returns (1, None, error containing operation name)
        ("frobnicate", None, "", 1, None, "frobnicate"),
    ],
)
def test_execute_protocol_matrix(
    operation, get_return, stdin_text, expected_code, expected_stdout, stderr_substr
):
    """execute() returns the expected (code, stdout, stderr) for each operation."""
    stdin = io.StringIO(stdin_text)

    if operation == "get" and get_return is not None or operation == "get":
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials",
            return_value=get_return,
        ):
            code, stdout, stderr = execute(operation, stdin)
    else:
        code, stdout, stderr = execute(operation, stdin)

    assert code == expected_code
    assert stdout == expected_stdout
    if stderr_substr is None:
        assert stderr is None
    else:
        assert stderr_substr in stderr


# ---------------------------------------------------------------------------
# 2. execute get-path boundary guards (broken-pipe + RuntimeError)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["raising_get_credentials", "broken_pipe_stdin"])
def test_execute_get_boundary_guard(scenario):
    """Exceptions inside execute('get', ...) never escape — degrade to (1, None, refusal).

    Retained guards:
    - broken-pipe: an OSError from stdin.read() is caught at the protocol boundary.
    - RuntimeError from get_credentials is caught the same way.
    """
    if scenario == "raising_get_credentials":
        stdin = io.StringIO("docker.cloudsmith.io")
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials",
            side_effect=RuntimeError("boom"),
        ):
            code, stdout, stderr = execute("get", stdin)
    else:
        # broken-pipe guard: stdin.read() itself raises an OSError
        class BrokenPipeStdin:
            def read(self):
                raise OSError("broken pipe")

        credential = CredentialResult(api_key="k_abc", source_name="test")
        code, stdout, stderr = execute(
            "get", BrokenPipeStdin(), credential=credential, api_host=None
        )

    assert code == 1
    assert stdout is None
    assert stderr == REFUSAL_MESSAGE


# ---------------------------------------------------------------------------
# 3. get_credentials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "server_url,credential,is_cloudsmith_return,expected",
    [
        # cloudsmith domain + creds → dict
        (
            "docker.cloudsmith.io",
            CredentialResult(api_key="k_xyz", source_name="test"),
            True,
            {"Username": "token", "Secret": "k_xyz"},
        ),
        # no credential → None (short-circuits before domain check)
        ("docker.cloudsmith.io", None, None, None),
        # non-cloudsmith domain → None
        (
            "evil.example.com",
            CredentialResult(api_key="k_xyz", source_name="test"),
            False,
            None,
        ),
    ],
)
def test_get_credentials(server_url, credential, is_cloudsmith_return, expected):
    """get_credentials returns a creds dict for valid CS domains, None otherwise."""
    if is_cloudsmith_return is None:
        # No domain check needed when credential is absent
        result = helper_get_credentials(server_url, credential=credential)
    else:
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.is_cloudsmith_domain",
            return_value=is_cloudsmith_return,
        ) as mock_check:
            result = helper_get_credentials(server_url, credential=credential)
        assert mock_check.call_args.kwargs["credential"] is credential

    assert result == expected


# ---------------------------------------------------------------------------
# 4. CLI wiring smoke test
# ---------------------------------------------------------------------------


def test_cli_no_arg_defaults_to_get(runner):
    """Invoking docker with no OPERATION defaults to 'get', emitting creds JSON.

    Proves the click shim is correctly wired to execute().
    """
    fake_creds = {"Username": "token", "Secret": "k_abc"}

    with patch(
        "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials",
        return_value=fake_creds,
    ):
        result = runner.invoke(
            docker,
            args=[],
            input="docker.cloudsmith.io",
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert json.dumps(fake_creds) in result.stdout


def test_execute_get_blank_stdin_returns_exit_1():
    """execute get with whitespace-only stdin → (1, missing-URL, 'No server URL...')."""
    stdin = io.StringIO(" \n")
    code, stdout, stderr = execute("get", stdin)

    assert code == 1
    assert stdout == "no credentials server URL"
    assert "No server URL provided" in stderr


# ---------------------------------------------------------------------------
# 5. BackendKind load-bearing values
# ---------------------------------------------------------------------------


def test_backend_kind_values():
    """DOCKER == 6 and NPM == 9 are load-bearing (used as integer wire values)."""
    assert BackendKind.DOCKER == 6
    assert BackendKind.NPM == 9


# ---------------------------------------------------------------------------
# 6. get_workspace_domains — HTTP status matrix
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)


@pytest.mark.parametrize(
    "status,expect_domains,expect_cached",
    [
        # 200 → records built and cached
        (200, True, True),
        # 404 → [] but NOT cached
        (404, False, False),
        # 403 → [] but NOT cached (may succeed after auth)
        (403, False, False),
        # 401 → [] but NOT cached (same branch as 403)
        (401, False, False),
        # 500 → [] and NOT cached
        (500, False, False),
    ],
)
@httpretty.activate(allow_net_connect=False)
def test_get_workspace_domains_status_matrix(
    tmp_path, monkeypatch, status, expect_domains, expect_cached
):
    """get_workspace_domains() caches or not based on HTTP status."""
    # redirect per-test (autouse fixture already set module-level path)
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    if status == 200:
        body = json.dumps(
            {"results": [_server_domain("docker.acme.com", "NATIVE_DOCKER")]}
        )
    else:
        body = json.dumps({"detail": "error"})

    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/v2/workspaces/acme/domains/",
        body=body,
        status=status,
        content_type="application/json",
    )

    credential = CredentialResult(api_key="k_abc", source_name="test")
    result = get_workspace_domains("acme", credential=credential, api_host=API_HOST)
    cache = read_cache(get_cache_path("acme", API_HOST))

    if expect_domains:
        assert len(result) == 1
        assert result[0].host == "docker.acme.com"
    else:
        assert result == []

    if expect_cached:
        assert cache is not None  # [] is falsy but not None
    else:
        assert cache is None

    # For the 200 case specifically, verify the auth header (X-Api-Key)
    if status == 200:
        assert httpretty.last_request().headers.get("X-Api-Key") == "k_abc"


@pytest.mark.parametrize(
    "status,expect_raise",
    [
        (200, False),
        (401, True),
        (403, True),
        (404, True),
        (500, True),
    ],
)
@httpretty.activate(allow_net_connect=False)
def test_get_workspace_domains_strict_raises_on_failure(
    tmp_path, monkeypatch, status, expect_raise
):
    """strict=True re-raises failures instead of degrading to [].

    Consumers presenting results to a user (`cloudsmith domains list`) must
    not render a typo'd org or an unreachable API as "no custom domains".
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    body = (
        json.dumps({"results": []})
        if status == 200
        else json.dumps({"detail": "error"})
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/v2/workspaces/acme/domains/",
        body=body,
        status=status,
        content_type="application/json",
    )

    credential = CredentialResult(api_key="k_abc", source_name="test")
    if expect_raise:
        with pytest.raises(ApiException):
            get_workspace_domains(
                "acme", credential=credential, api_host=API_HOST, strict=True
            )
    else:
        result = get_workspace_domains(
            "acme", credential=credential, api_host=API_HOST, strict=True
        )
        assert result == []


@httpretty.activate(allow_net_connect=False)
def test_get_workspace_domains_caches_an_empty_listing(tmp_path, monkeypatch):
    """A Workspace with no domains answers 200 with an empty array.

    That is a real answer rather than a failure, so it is cached like any
    other: a second lookup within the TTL must be served from the cache
    instead of asking again.
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/v2/workspaces/acme/domains/",
        body=json.dumps({"results": []}),
        status=200,
        content_type="application/json",
    )
    credential = CredentialResult(api_key="k_abc", source_name="test")

    assert get_workspace_domains("acme", credential=credential, api_host=API_HOST) == []
    assert read_cache(get_cache_path("acme", API_HOST)) == []
    assert len(httpretty.latest_requests()) == 1

    assert get_workspace_domains("acme", credential=credential, api_host=API_HOST) == []
    assert len(httpretty.latest_requests()) == 1


@httpretty.activate(allow_net_connect=False)
def test_get_workspace_domains_bearer_credential_sends_authorization_header(
    tmp_path, monkeypatch
):
    """A bearer credential authenticates the lookup with its own header scheme.

    The credential object flows through to the API layer unmodified, so an
    SAML access token goes out as ``Authorization: Bearer``, never ``X-Api-Key``.
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/v2/workspaces/acme/domains/",
        body=json.dumps({"results": []}),
        status=200,
        content_type="application/json",
    )

    initialise_api(
        host=API_HOST,
        credential=CredentialResult(api_key="k_stale", source_name="test"),
    )
    credential = CredentialResult(
        api_key="jwt_token", source_name="test", auth_type="bearer"
    )
    get_workspace_domains("acme", credential=credential, api_host=API_HOST)

    headers = httpretty.last_request().headers
    assert headers.get("Authorization") == "Bearer jwt_token"
    assert headers.get("X-Api-Key") is None


# ---------------------------------------------------------------------------
# 7. get_workspace_domains — cache edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario,expected",
    [
        # legacy string-list cache → miss (re-fetch required); retains legacy-cache guard
        ("legacy_string_list", None),
        # empty [] cache → hit (valid cached 'no domains')
        ("empty_list", []),
    ],
)
def test_get_workspace_domains_cache_edge(tmp_path, monkeypatch, scenario, expected):
    """Cache format edge cases: legacy string-list is a miss; empty list is a hit."""
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    cache_path = get_cache_path("acme")

    if scenario == "legacy_string_list":
        # A real legacy document predates format_version, which is what makes
        # it a miss - stamping the current version on it would describe a
        # document no build has ever written.
        data = {"domains": ["docker.acme.com"], "cached_at": time.time()}
    else:
        data = {
            "format_version": CACHE_FORMAT_VERSION,
            "domains": [],
            "cached_at": time.time(),
        }

    cache_path.write_text(json.dumps(data), encoding="utf-8")
    assert read_cache(cache_path) == expected


def test_cache_that_is_not_utf8_reads_as_a_miss(tmp_path, monkeypatch):
    """A cache file of undecodable bytes is a miss, not a crash."""
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    cache_path = get_cache_path("acme")
    cache_path.write_bytes(b"\xff\xfe not utf-8 at all")

    assert read_cache(cache_path) is None
    assert not read_all_cached_domains()


def test_unwritable_config_dir_reads_as_no_cached_domains(tmp_path, monkeypatch):
    """An unwritable config directory yields no cached domains, not a crash."""
    read_only = tmp_path / "read-only"
    read_only.mkdir(mode=0o500)
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(read_only),
    )

    assert not read_all_cached_domains()


# ---------------------------------------------------------------------------
# 8. get_format_domains
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_get_format_domains_filters_correctly(tmp_path, monkeypatch):
    """get_format_domains returns only the Docker hosts, in the server's order.

    Mixed body: a custom and a Cloudsmith-owned Docker host (included), an npm
    host and the download CDN (excluded).
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    body = {
        "results": [
            _server_domain("docker.acme.com", "NATIVE_DOCKER"),
            _server_domain("npm.acme.com", "NATIVE_NPM"),
            _server_domain("dl.acme.com", "DOWNLOAD"),
            _server_domain("docker.cloudsmith.io", "NATIVE_DOCKER", "GLOBAL"),
        ]
    }
    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/v2/workspaces/acme/domains/",
        body=json.dumps(body),
        status=200,
        content_type="application/json",
    )

    hosts = get_format_domains(
        "acme",
        BackendKind.DOCKER,
        credential=CredentialResult(api_key="k", source_name="test"),
        api_host=API_HOST,
    )

    assert hosts == ["docker.acme.com", "docker.cloudsmith.io"]


def test_get_format_domains_forwards_configure_api(monkeypatch):
    """A caller that has already configured the SDK can say so."""
    recorded = {}

    def _fake_get_workspace_domains(workspace, **kwargs):
        recorded.update(kwargs)
        return []

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_workspace_domains",
        _fake_get_workspace_domains,
    )

    get_format_domains("acme", BackendKind.DOCKER, configure_api=False)

    assert recorded["configure_api"] is False


# ---------------------------------------------------------------------------
# 9. is_cloudsmith_domain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,org,cached_domains,backend_kind,expected",
    [
        # Standard *.cloudsmith.io → True (no API)
        ("docker.cloudsmith.io", None, None, None, True),
        ("dl.cloudsmith.io", None, None, None, True),
        # Standard *.cloudsmith.com → True (no API)
        ("docker.cloudsmith.com", None, None, None, True),
        # Non-cloudsmith → False
        ("evil.example.com", None, None, None, False),
        # Custom domain the server listed → True
        (
            "docker.acme.com",
            "acme",
            [_server_domain("docker.acme.com", "NATIVE_DOCKER")],
            None,
            True,
        ),
        # Host the server did not list → False
        (
            "docker.acme.com",
            "acme",
            [_server_domain("npm.acme.com", "NATIVE_NPM")],
            None,
            False,
        ),
        # backend_kind=DOCKER: docker custom domain → True
        (
            "docker.acme.com",
            "acme",
            [_server_domain("docker.acme.com", "NATIVE_DOCKER")],
            BackendKind.DOCKER,
            True,
        ),
        # backend_kind=DOCKER: npm custom domain → False
        (
            "npm.acme.com",
            "acme",
            [_server_domain("npm.acme.com", "NATIVE_NPM")],
            BackendKind.DOCKER,
            False,
        ),
        # UPPERCASE custom host row with backend_kind=DOCKER — guards the
        # get_format_domains() casing path (the branch the lowercase fix touched)
        (
            "DOCKER.ACME.COM",
            "acme",
            [_server_domain("docker.acme.com", "NATIVE_DOCKER")],
            BackendKind.DOCKER,
            True,
        ),
    ],
)
def test_is_cloudsmith_domain(
    tmp_path, monkeypatch, host, org, cached_domains, backend_kind, expected
):
    """is_cloudsmith_domain returns correct bool for standard, custom, and edge cases."""
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    if cached_domains is not None:
        write_cache(get_cache_path(org, API_HOST), org, cached_domains)

    kwargs = {
        "credential": CredentialResult(api_key="k_abc", source_name="test"),
        "api_host": API_HOST,
        "org": org,
    }
    if backend_kind is not None:
        kwargs["backend_kind"] = backend_kind

    result = is_cloudsmith_domain(host, **kwargs)
    assert result is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        # Standard apex + subdomains, any scheme/path/casing → True
        ("cloudsmith.io", True),
        ("cloudsmith.com", True),
        ("docker.cloudsmith.io", True),
        ("https://terraform.cloudsmith.io/acme/repo/", True),
        ("TERRAFORM.CLOUDSMITH.COM", True),
        # Custom domains and foreign hosts → False (never standard)
        ("tf.acme.com", False),
        ("docker.acme.com", False),
        ("evil.example.com", False),
        # Lookalikes that must not match the suffix check
        ("notcloudsmith.io", False),
        ("cloudsmith.io.evil.com", False),
        ("", False),
    ],
)
def test_is_standard_cloudsmith_domain(url, expected):
    """Only *.cloudsmith.io/.com (and the apexes) are standard; custom domains
    and lookalikes are not — no API/auth is consulted."""
    assert is_standard_cloudsmith_domain(url) is expected


# ---------------------------------------------------------------------------
# 10. Docker runtime backend_kind wiring
# ---------------------------------------------------------------------------


def test_get_credentials_refuses_npm_custom_domain(tmp_path, monkeypatch):
    """get_credentials for an NPM custom domain → None (runtime passes BackendKind.DOCKER).

    Proves the runtime passes backend_kind=DOCKER to is_cloudsmith_domain.
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    write_cache(
        get_cache_path("acme", API_HOST),
        "acme",
        [_server_domain("npm.acme.com", "NATIVE_NPM")],
    )

    credential = CredentialResult(api_key="k_xyz", source_name="test")
    result = helper_get_credentials(
        "npm.acme.com", credential=credential, api_host=API_HOST
    )

    assert result is None
