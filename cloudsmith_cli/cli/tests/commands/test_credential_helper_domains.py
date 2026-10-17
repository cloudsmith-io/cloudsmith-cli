# Copyright 2026 Cloudsmith Ltd
"""Tests for reading the server's Workspace domain records and caching them."""

import subprocess
import sys
from unittest.mock import patch

import cloudsmith_api
import pytest

from ....credential_helpers.backends import BackendKind
from ....credential_helpers.domains import (
    DomainScope,
    DomainType,
    domain_from_payload,
    get_cache_path,
    get_format_domains,
    read_all_cached_domains,
    read_cache,
    write_cache,
)


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )


def _payload(name, domain_type, scope="GLOBAL", repository=None):
    return {
        "domain_name": name,
        "domain_type": domain_type,
        "domain_scope": scope,
        "repository": repository,
    }


def _record(*args, **kwargs):
    """Parse one server record that this CLI is expected to understand."""
    record = domain_from_payload(_payload(*args, **kwargs), "acme")
    assert record is not None
    return record


@pytest.mark.parametrize(
    "server_type,domain_type,backend_kind",
    [
        ("DOWNLOAD", DomainType.DOWNLOAD, None),
        ("UPLOAD", DomainType.UPLOAD, None),
        ("CLOUDSMITH_API", DomainType.CLOUDSMITH_API, None),
        ("NATIVE_DOCKER", DomainType.NATIVE_API, BackendKind.DOCKER),
        ("NATIVE_HELM_OCI", DomainType.NATIVE_API, BackendKind.HELM),
        ("NATIVE_GO", DomainType.NATIVE_API, BackendKind.GO),
    ],
)
def test_server_domain_types_map_to_a_purpose_and_format(
    server_type, domain_type, backend_kind
):
    """A native type names its package format; the others serve no single one."""
    record = _record("host.example.com", server_type)

    assert record.domain_type is domain_type
    assert record.backend_kind == backend_kind


@pytest.mark.parametrize("server_type", ["NATIVE_SOMETHING_NEW", "MIRROR", None])
def test_a_domain_type_this_cli_does_not_know_is_skipped(server_type):
    """The server adds types over time; an unknown one is not guessed at."""
    assert domain_from_payload(_payload("x.example.com", server_type), "acme") is None


def test_a_domain_scope_this_cli_does_not_know_is_skipped():
    """An unknown scope cannot say whom the domain serves, so it is not guessed."""
    payload = _payload("x.example.com", "DOWNLOAD", scope="ORGANIZATION_UNIT")

    assert domain_from_payload(payload, "acme") is None


def test_a_cloudsmith_owned_domain_belongs_to_no_workspace():
    """A GLOBAL domain serves every Workspace, so it is not attributed to one."""
    record = _record("dl.cloudsmith.io", "DOWNLOAD")

    assert record.scope is DomainScope.GLOBAL
    assert record.is_custom is False
    assert record.workspace is None


def test_a_custom_domain_keeps_its_workspace_and_repository():
    """A REPOSITORY domain says which repository it is restricted to."""
    record = _record("dl.acme.com", "DOWNLOAD", "REPOSITORY", "prod")

    assert record.is_custom is True
    assert record.workspace == "acme"
    assert record.serves_repository("prod")
    assert not record.serves_repository("dev")


def test_cache_round_trip_keeps_the_server_order(tmp_path):
    """The cache holds the server's answer, so a cached run sees the same order."""
    payload = [
        _payload("docker.acme.com", "NATIVE_DOCKER", "WORKSPACE"),
        _payload("docker.cloudsmith.io", "NATIVE_DOCKER"),
    ]
    cache_path = tmp_path / "acme.json"
    write_cache(cache_path, "acme", payload)

    assert [d.host for d in read_cache(cache_path) or []] == [
        "docker.acme.com",
        "docker.cloudsmith.io",
    ]


def test_each_api_host_has_its_own_cache():
    """A Workspace slug on one API host is a different Workspace on another.

    Sharing one cache entry would hand one host's domains to a run on the other.
    """
    production = get_cache_path("acme", "https://api.cloudsmith.io")
    other = get_cache_path("acme", "https://api.example.com")

    assert production != other


@pytest.mark.parametrize(
    "other_base",
    [
        "http://api.example.com",
        "https://api.example.com:8443",
        "https://api.example.com/tenant",
    ],
)
def test_api_bases_on_one_hostname_have_their_own_cache(other_base):
    """A different scheme, port or path is a different Cloudsmith."""
    assert get_cache_path("acme", "https://api.example.com") != get_cache_path(
        "acme", other_base
    )


def test_a_trailing_slash_does_not_change_the_cache():
    """The same API base with a trailing slash uses the same cache."""
    assert get_cache_path("acme", "https://api.example.com/") == get_cache_path(
        "acme", "https://api.example.com"
    )


def test_no_api_host_uses_the_cache_of_the_default_api_host():
    """Without an API host, the cache is the one for the default API host."""
    assert get_cache_path("acme") == get_cache_path(
        "acme", cloudsmith_api.Configuration().host
    )


def test_no_api_host_uses_the_cache_of_the_configured_sdk_host(monkeypatch):
    """Without an API host, the cache is the one for the host the SDK calls.

    A request then never fills the cache of another API host.
    """
    config = cloudsmith_api.Configuration()
    config.host = "https://api.example.com"
    monkeypatch.setattr(cloudsmith_api.Configuration, "_default", config)

    assert get_cache_path("acme") == get_cache_path("acme", "https://api.example.com")


def test_a_cache_lookup_does_not_import_the_sdk():
    """A credential helper that hits the cache does not pay for the SDK import."""
    code = (
        "import sys\n"
        "from cloudsmith_cli.credential_helpers.domains import "
        "get_cache_path\n"
        "get_cache_path('acme')\n"
        "print('cloudsmith_api' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


def test_cached_domains_are_read_for_the_current_api_host_only():
    """A no-Workspace listing on one API host never shows another host's domains."""
    write_cache(
        get_cache_path("acme", "https://api.cloudsmith.io"),
        "acme",
        [_payload("dl.cloudsmith.io", "DOWNLOAD")],
    )
    write_cache(
        get_cache_path("acme", "https://api.example.com"),
        "acme",
        [_payload("dl.example.com", "DOWNLOAD")],
    )

    hosts = [d.host for d in read_all_cached_domains("https://api.example.com")]

    assert hosts == ["dl.example.com"]


def test_format_domains_keep_the_server_preference_order():
    """The first host is the one the server prefers, Cloudsmith-owned last."""
    records = [
        _record(name, server_type, scope)
        for name, server_type, scope in [
            ("docker.acme.com", "NATIVE_DOCKER", "WORKSPACE"),
            ("npm.acme.com", "NATIVE_NPM", "WORKSPACE"),
            ("dl.cloudsmith.io", "DOWNLOAD", "GLOBAL"),
            ("docker.cloudsmith.io", "NATIVE_DOCKER", "GLOBAL"),
        ]
    ]

    with patch(
        "cloudsmith_cli.credential_helpers.domains.get_workspace_domains",
        return_value=records,
    ):
        hosts = get_format_domains("acme", BackendKind.DOCKER)

    assert hosts == ["docker.acme.com", "docker.cloudsmith.io"]
