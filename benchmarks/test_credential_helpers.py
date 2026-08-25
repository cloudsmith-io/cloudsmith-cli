# Copyright 2026 Cloudsmith Ltd
"""CodSpeed benchmarks for the credential helper flows.

Run with ``pytest benchmarks/ --codspeed``. Each benchmark measures one
in-process flow that a credential helper runs on each invocation. No
benchmark touches the network: the custom-domain flow is served from a
pre-warmed cache.
"""

import io
import json

import pytest

from cloudsmith_cli.core.credentials.chain import CredentialProviderChain
from cloudsmith_cli.core.credentials.models import CredentialContext, CredentialResult
from cloudsmith_cli.credential_helpers import custom_domains
from cloudsmith_cli.credential_helpers.backends import BackendKind
from cloudsmith_cli.credential_helpers.cargo import runtime as cargo_runtime
from cloudsmith_cli.credential_helpers.common import is_cloudsmith_domain
from cloudsmith_cli.credential_helpers.custom_domains import CustomDomain, write_cache
from cloudsmith_cli.credential_helpers.default_domains import (
    DomainType,
    load_default_domains,
)
from cloudsmith_cli.credential_helpers.docker import runtime as docker_runtime
from cloudsmith_cli.credential_helpers.pnpm import runtime as pnpm_runtime

API_KEY = "0123456789abcdef0123456789abcdef"

ORG = "acme"

CARGO_GET_REQUEST = json.dumps(
    {
        "v": 1,
        "kind": "get",
        "operation": "read",
        "registry": {"index-url": f"sparse+https://cargo.cloudsmith.io/{ORG}/repo/"},
    }
)


@pytest.fixture
def credential():
    return CredentialResult(api_key=API_KEY, source_name="env_var")


@pytest.fixture
def warm_custom_domain_cache(monkeypatch, tmp_path):
    domain = CustomDomain(
        host="cargo.example.com",
        backend_kind=int(BackendKind.CARGO),
        enabled=True,
        validated=True,
        org=ORG,
        domain_type=DomainType.NATIVE_API,
    )
    monkeypatch.setattr(custom_domains, "get_cache_dir", lambda: tmp_path)
    write_cache(custom_domains.get_cache_path(ORG), [domain])
    return domain


def test_cargo_session(benchmark, credential):
    def run_session():
        stdin = io.StringIO(CARGO_GET_REQUEST + "\n")
        return cargo_runtime.execute(stdin, io.StringIO(), credential=credential)

    exit_code, stderr_text = benchmark(run_session)
    assert exit_code == 0
    assert stderr_text is None


def test_cargo_handle_request(benchmark, credential):
    request = json.loads(CARGO_GET_REQUEST)
    response = benchmark(cargo_runtime.handle_request, request, credential=credential)
    assert response["Ok"]["token"] == API_KEY


def test_docker_get(benchmark, credential):
    def run_get():
        stdin = io.StringIO("https://docker.cloudsmith.io\n")
        return docker_runtime.execute("get", stdin, credential=credential)

    exit_code, stdout_text, _ = benchmark(run_get)
    assert exit_code == 0
    assert json.loads(stdout_text)["Secret"] == API_KEY


def test_pnpm_get(benchmark, credential):
    exit_code, token, _ = benchmark(
        pnpm_runtime.execute,
        f"https://npm.cloudsmith.io/{ORG}/repo/",
        credential=credential,
    )
    assert exit_code == 0
    assert token == API_KEY


def test_standard_domain_match(benchmark, credential):
    matched = benchmark(
        is_cloudsmith_domain,
        f"https://cargo.cloudsmith.io/{ORG}/repo/",
        credential=credential,
        backend_kind=BackendKind.CARGO,
        org=ORG,
    )
    assert matched is True


def test_custom_domain_match_from_cache(
    benchmark, credential, warm_custom_domain_cache
):
    matched = benchmark(
        is_cloudsmith_domain,
        f"https://{warm_custom_domain_cache.host}/{ORG}/repo/",
        credential=credential,
        backend_kind=BackendKind.CARGO,
        org=ORG,
    )
    assert matched is True


def test_load_default_domains(benchmark):
    domains = benchmark(load_default_domains)
    assert domains


def test_credential_chain_resolves_env_var(benchmark):
    def resolve():
        chain = CredentialProviderChain()
        return chain.resolve(CredentialContext(api_key_from_env=API_KEY))

    result = benchmark(resolve)
    assert result is not None
    assert result.api_key == API_KEY
