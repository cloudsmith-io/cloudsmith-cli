# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper pnpm` runtime and CLI shim.

pnpm's ``tokenHelper`` protocol is a plain-text one-shot: the helper prints the
complete ``Authorization`` header value (no newline) on stdout and exits, and
pnpm forwards that value verbatim to the registry.  There is no handshake and
no request stream — everything the runtime does happens in a single call.

The helper picks the HTTP authorization scheme so pnpm never has to guess:
Cloudsmith API keys use the ``token`` scheme and SSO/OIDC credentials use
``Bearer``.  These tests pin that behaviour for both credential kinds.
"""

from __future__ import annotations

from unittest.mock import patch

import click.testing
import pytest

from ...core.credentials.models import CredentialResult
from ...credential_helpers.backends import BackendKind
from ...credential_helpers.pnpm.runtime import (
    _REFUSAL_MESSAGE,
    execute,
    get_pnpm_credentials,
)
from ..commands.credential_helper.pnpm import pnpm

CLOUDSMITH_HOST = "npm.cloudsmith.io"
FOREIGN_HOST = "registry.npmjs.org"


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


@pytest.fixture()
def credential():
    """Return a resolved API-key credential."""
    return CredentialResult(api_key="k_abc", source_name="test")


@pytest.fixture()
def sso_credential():
    """Return a resolved bearer (SSO / OIDC) credential."""
    return CredentialResult(
        api_key="jwt_token",
        source_name="keyring",
        auth_type="bearer",
    )


# ---------------------------------------------------------------------------
# 1. get_pnpm_credentials — the credential path
# ---------------------------------------------------------------------------


def test_get_returns_token_scheme_for_api_key_credential(credential):
    """A Cloudsmith registry URL yields ``token <api_key>`` for an API-key credential.

    Regression guard: pnpm forwards the helper's output verbatim as the
    ``Authorization`` header, so the scheme must come from the helper — not
    from pnpm.  Cloudsmith API keys authenticate with the ``token`` scheme.
    """
    assert get_pnpm_credentials(CLOUDSMITH_HOST, credential=credential) == (
        "token k_abc"
    )


def test_get_uses_bearer_scheme_for_sso_credential(sso_credential):
    """An SSO/OIDC credential is returned under the ``Bearer`` scheme.

    Mirrors the Cargo helper's scheme selection: ``auth_type == "bearer"``
    (a JWT from the OIDC exchange or an SSO refresh) means ``Bearer``, and
    anything else — practically, an API key — means ``token``.
    """
    assert get_pnpm_credentials(CLOUDSMITH_HOST, credential=sso_credential) == (
        "Bearer jwt_token"
    )


def test_get_accepts_a_full_https_url(credential):
    """The URL argument may include the scheme and path — hostname is what matters."""
    url = f"https://{CLOUDSMITH_HOST}/acme/repo/"
    assert get_pnpm_credentials(url, credential=credential) == "token k_abc"


def test_get_uses_the_npm_backend_kind_for_custom_domains(credential):
    """Custom-domain matching is scoped to NPM-backed domains."""
    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.runtime.is_cloudsmith_domain",
        return_value=True,
    ) as mock_check:
        get_pnpm_credentials("https://npm.acme.com/", credential=credential, org="acme")

    assert mock_check.call_args.kwargs["backend_kind"] is BackendKind.NPM
    assert mock_check.call_args.kwargs["org"] == "acme"


# ---------------------------------------------------------------------------
# 2. get_pnpm_credentials — the refusal paths
# ---------------------------------------------------------------------------


def test_get_returns_none_without_a_credential():
    """A missing credential means no helper output, and no exception."""
    assert get_pnpm_credentials(CLOUDSMITH_HOST, credential=None) is None


def test_get_returns_none_for_a_credential_without_an_api_key():
    """An empty api_key is treated as no credential at all."""
    empty = CredentialResult(api_key="", source_name="test")
    assert get_pnpm_credentials(CLOUDSMITH_HOST, credential=empty) is None


def test_get_returns_none_for_a_foreign_registry(credential):
    """A non-Cloudsmith registry gets no token — the helper must not leak it."""
    assert get_pnpm_credentials(FOREIGN_HOST, credential=credential) is None


def test_get_returns_none_when_custom_domain_lookup_rejects(credential):
    """A custom domain the API refuses is not considered a Cloudsmith registry."""
    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.runtime.is_cloudsmith_domain",
        return_value=False,
    ):
        assert (
            get_pnpm_credentials(
                "https://npm.acme.com/", credential=credential, org="acme"
            )
            is None
        )


# ---------------------------------------------------------------------------
# 3. execute — the tuple contract
# ---------------------------------------------------------------------------


def test_execute_returns_token_scheme_for_api_key_credential(credential):
    """Happy path for an API key: exit-0, ``token <api_key>`` on stdout, no stderr."""
    exit_code, stdout, stderr = execute(CLOUDSMITH_HOST, credential=credential)

    assert (exit_code, stderr) == (0, None)
    assert stdout == "token k_abc"


def test_execute_returns_bearer_for_sso_credential(sso_credential):
    """SSO/OIDC credentials use the ``Bearer`` scheme end-to-end through execute()."""
    _, stdout, _ = execute(CLOUDSMITH_HOST, credential=sso_credential)

    assert stdout == "Bearer jwt_token"


def test_execute_refuses_without_credentials():
    """No credential is a hard refusal (exit 1) with a refusal message on stderr."""
    exit_code, stdout, stderr = execute(CLOUDSMITH_HOST, credential=None)

    assert (exit_code, stdout, stderr) == (1, None, _REFUSAL_MESSAGE)


def test_execute_refuses_for_a_foreign_registry(credential):
    """A registry we don't serve is not our concern — exit 1, no leaked token."""
    exit_code, stdout, stderr = execute(FOREIGN_HOST, credential=credential)

    assert (exit_code, stdout, stderr) == (1, None, _REFUSAL_MESSAGE)


def test_execute_degrades_cleanly_on_domain_lookup_failure(credential):
    """A network/SDK error during custom-domain discovery must not raise."""
    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.runtime.is_cloudsmith_domain",
        side_effect=RuntimeError("boom"),
    ):
        exit_code, stdout, stderr = execute(
            "https://npm.acme.com/", credential=credential, org="acme"
        )

    assert (exit_code, stdout) == (1, None)
    assert stderr == _REFUSAL_MESSAGE


# ---------------------------------------------------------------------------
# 4. CLI wiring
# ---------------------------------------------------------------------------


def test_cli_prints_token_without_a_trailing_newline(runner):
    """The click shim writes stdin/stdout through — pnpm consumes the whole line
    as a header value, so a trailing newline would poison the request.
    """
    result = runner.invoke(
        pnpm,
        args=["-k", "k_abc", CLOUDSMITH_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    # No newline: pnpm reads the token as-is into the Authorization header.
    assert result.stdout == "token k_abc"


def test_cli_defaults_to_npm_cloudsmith_io_when_no_repo_argument(runner):
    """Omitting the URL argument still works — the default host is Cloudsmith's."""
    result = runner.invoke(
        pnpm,
        args=["-k", "k_abc"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout == "token k_abc"


def test_cli_exits_non_zero_with_a_hint_when_no_credential_resolves(runner):
    """A missing credential is exit-1 with a refusal on stderr and no token stdout."""
    # Patch the provider chain rather than relying on env vars: a developer's
    # local ~/.cloudsmith/config.ini (or an active profile) can otherwise
    # resolve a credential and turn this into a false negative.
    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        return_value=None,
    ):
        result = runner.invoke(
            pnpm,
            args=[CLOUDSMITH_HOST],
            env={"CLOUDSMITH_API_KEY": ""},
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    # No token must leak on stdout on the refusal path.
    assert result.stdout == ""


def test_cli_exits_non_zero_for_a_foreign_registry(runner):
    """A non-Cloudsmith host is a refusal even when a credential is available."""
    result = runner.invoke(
        pnpm,
        args=["-k", "k_abc", FOREIGN_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "k_abc" not in result.stdout
