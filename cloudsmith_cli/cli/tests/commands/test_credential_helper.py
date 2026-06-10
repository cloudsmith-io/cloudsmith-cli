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
    _REFUSAL_MESSAGE,
    execute,
    get_credentials as helper_get_credentials,
)

API_HOST = "https://api.cloudsmith.io"


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
        # get-refusal: get_credentials returns None → (1, None, refusal)
        ("get", None, "evil.example.com", 1, None, "Unable to retrieve credentials"),
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

    if operation == "get" and get_return is not None:
        with patch(
            "cloudsmith_cli.credential_helpers.docker.runtime.get_credentials",
            return_value=get_return,
        ):
            code, stdout, stderr = execute(operation, stdin)
    elif operation == "get":
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
    assert stderr == _REFUSAL_MESSAGE


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
        ):
            result = helper_get_credentials(server_url, credential=credential)

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


def test_execute_get_empty_stdin_returns_exit_1():
    """execute get with empty stdin → (1, None, 'No server URL...')."""
    stdin = io.StringIO("")
    code, stdout, stderr = execute("get", stdin)

    assert code == 1
    assert stdout is None
    assert "No server URL provided" in stderr


# ---------------------------------------------------------------------------
# 5. BackendKind load-bearing values
# ---------------------------------------------------------------------------


def test_backend_kind_values():
    """DOCKER == 6 and NPM == 9 are load-bearing (used as integer wire values)."""
    assert BackendKind.DOCKER == 6
    assert BackendKind.NPM == 9


# ---------------------------------------------------------------------------
# 6. get_custom_domains — HTTP status matrix
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
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


@pytest.mark.parametrize(
    "status,expect_domains,expect_cached",
    [
        # 200 → records built and cached
        (200, True, True),
        # 402 → [] and cached (feature not enabled)
        (402, False, True),
        # 404 → [] and cached (org not found)
        (404, False, True),
        # 403 → [] but NOT cached (may succeed after auth)
        (403, False, False),
        # 401 → [] but NOT cached (same branch as 403)
        (401, False, False),
        # 500 → [] and NOT cached
        (500, False, False),
    ],
)
@httpretty.activate(allow_net_connect=False)
def test_get_custom_domains_status_matrix(
    tmp_path, monkeypatch, status, expect_domains, expect_cached
):
    """get_custom_domains() caches or not based on HTTP status."""
    # redirect per-test (autouse fixture already set module-level path)
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    if status == 200:
        body = json.dumps(
            [
                {
                    "host": "docker.acme.com",
                    "backend_kind": 6,
                    "domain_type": 1,
                    "enabled": True,
                    "validated": True,
                }
            ]
        )
    else:
        body = json.dumps({"detail": "error"})

    httpretty.register_uri(
        httpretty.GET,
        f"{API_HOST}/orgs/acme/custom-domains/",
        body=body,
        status=status,
        content_type="application/json",
    )

    result = get_custom_domains("acme", api_key="k_abc", api_host=API_HOST)
    cache = read_cache(get_cache_path("acme"))

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


# ---------------------------------------------------------------------------
# 7. get_custom_domains — cache edge cases
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
def test_get_custom_domains_cache_edge(tmp_path, monkeypatch, scenario, expected):
    """Cache format edge cases: legacy string-list is a miss; empty list is a hit."""
    import time

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    cache_path = get_cache_path("acme")

    if scenario == "legacy_string_list":
        data = {"domains": ["docker.acme.com"], "cached_at": time.time()}
    else:
        data = {"domains": [], "cached_at": time.time()}

    cache_path.write_text(json.dumps(data), encoding="utf-8")
    assert read_cache(cache_path) == expected


# ---------------------------------------------------------------------------
# 8. get_format_domains
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_get_format_domains_filters_correctly(tmp_path, monkeypatch):
    """get_format_domains returns only enabled+validated Docker hosts.

    Mixed body: docker enabled+validated (included), npm (excluded),
    disabled docker (excluded), unvalidated docker (excluded), backend_kind=None (excluded).
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    body = [
        # Included: Docker, enabled, validated
        {
            "host": "docker.acme.com",
            "backend_kind": 6,
            "domain_type": 1,
            "enabled": True,
            "validated": True,
        },
        # Excluded: NPM backend
        {
            "host": "npm.acme.com",
            "backend_kind": 9,
            "domain_type": 1,
            "enabled": True,
            "validated": True,
        },
        # Excluded: disabled
        {
            "host": "docker2.acme.com",
            "backend_kind": 6,
            "domain_type": 1,
            "enabled": False,
            "validated": True,
        },
        # Excluded: unvalidated
        {
            "host": "docker3.acme.com",
            "backend_kind": 6,
            "domain_type": 1,
            "enabled": True,
            "validated": False,
        },
        # Excluded: backend_kind=None (download domain)
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


# ---------------------------------------------------------------------------
# 9. is_cloudsmith_domain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,env_org,cached_domains,backend_kind,expected",
    [
        # Standard *.cloudsmith.io → True (no API)
        ("docker.cloudsmith.io", None, None, None, True),
        ("dl.cloudsmith.io", None, None, None, True),
        # Standard *.cloudsmith.com → True (no API)
        ("docker.cloudsmith.com", None, None, None, True),
        # Non-cloudsmith → False
        ("evil.example.com", None, None, None, False),
        # Custom enabled+validated → True
        (
            "docker.acme.com",
            "acme",
            [
                CustomDomain(
                    host="docker.acme.com", backend_kind=6, enabled=True, validated=True
                )
            ],
            None,
            True,
        ),
        # Custom disabled → False
        (
            "docker.acme.com",
            "acme",
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=False,
                    validated=True,
                )
            ],
            None,
            False,
        ),
        # Custom enabled but unvalidated → False
        (
            "docker.acme.com",
            "acme",
            [
                CustomDomain(
                    host="docker.acme.com",
                    backend_kind=6,
                    enabled=True,
                    validated=False,
                )
            ],
            None,
            False,
        ),
        # backend_kind=DOCKER: docker custom domain → True
        (
            "docker.acme.com",
            "acme",
            [
                CustomDomain(
                    host="docker.acme.com", backend_kind=6, enabled=True, validated=True
                )
            ],
            BackendKind.DOCKER,
            True,
        ),
        # backend_kind=DOCKER: npm custom domain → False
        (
            "npm.acme.com",
            "acme",
            [
                CustomDomain(
                    host="npm.acme.com", backend_kind=9, enabled=True, validated=True
                )
            ],
            BackendKind.DOCKER,
            False,
        ),
        # UPPERCASE custom host row with backend_kind=DOCKER — guards the
        # get_format_domains() casing path (the branch the lowercase fix touched)
        (
            "DOCKER.ACME.COM",
            "acme",
            [
                CustomDomain(
                    host="docker.acme.com", backend_kind=6, enabled=True, validated=True
                )
            ],
            BackendKind.DOCKER,
            True,
        ),
    ],
)
def test_is_cloudsmith_domain(
    tmp_path, monkeypatch, host, env_org, cached_domains, backend_kind, expected
):
    """is_cloudsmith_domain returns correct bool for standard, custom, and edge cases."""
    from ....credential_helpers.common import is_cloudsmith_domain

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    if env_org:
        monkeypatch.setenv("CLOUDSMITH_ORG", env_org)
    else:
        monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)

    if cached_domains is not None:
        write_cache(get_cache_path(env_org), cached_domains)

    kwargs = {"api_key": "k_abc", "api_host": API_HOST}
    if backend_kind is not None:
        kwargs["backend_kind"] = backend_kind

    result = is_cloudsmith_domain(host, **kwargs)
    assert result is expected


# ---------------------------------------------------------------------------
# 10. Docker runtime backend_kind wiring
# ---------------------------------------------------------------------------


def test_get_credentials_refuses_npm_custom_domain(tmp_path, monkeypatch):
    """get_credentials for an NPM custom domain → None (runtime passes BackendKind.DOCKER).

    Proves the runtime passes backend_kind=DOCKER to is_cloudsmith_domain.
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    cache_path = get_cache_path("acme")
    write_cache(
        cache_path,
        [
            CustomDomain(
                host="npm.acme.com", backend_kind=9, enabled=True, validated=True
            )
        ],
    )

    credential = CredentialResult(api_key="k_xyz", source_name="test")
    result = helper_get_credentials(
        "npm.acme.com", credential=credential, api_host=API_HOST
    )

    assert result is None
