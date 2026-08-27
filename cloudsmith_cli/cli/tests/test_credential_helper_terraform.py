# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper terraform` runtime, CLI shim
and the ``terraform-credentials-cloudsmith`` wrapper binary.

Terraform's credentials-helper protocol is a one-shot per request: it runs the
helper as ``terraform-credentials-cloudsmith [args...] <verb> <hostname>`` and,
for ``get``, expects either a JSON credentials object (``{"token": "..."}``) or
an empty object (``{}``) on stdout with exit 0, or an end-user-oriented error on
stderr with a non-zero exit.

These tests pin the three ``get`` outcomes (token / empty-object / refusal),
the rejection of ``store``/``forget`` and unknown verbs, and that the wrapper
delegates ``get`` to the CLI while answering everything else itself.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import click.testing
import pytest

from ...core.credentials.models import CredentialResult
from ...credential_helpers.backends import BackendKind
from ...credential_helpers.terraform import wrapper
from ...credential_helpers.terraform.runtime import (
    _MISSING_ORG_MESSAGE,
    _REFUSAL_MESSAGE,
    execute,
    get_token,
)
from ..commands.credential_helper.terraform import terraform

CLOUDSMITH_HOST = "terraform.cloudsmith.io"
FOREIGN_HOST = "registry.terraform.io"


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


@pytest.fixture()
def credential():
    """Return a resolved API-key credential."""
    return CredentialResult(api_key="k_abc", source_name="test")


# ---------------------------------------------------------------------------
# 1. get_token — the credential path
# ---------------------------------------------------------------------------


def test_get_token_returns_api_key_for_cloudsmith_host(credential):
    """A Cloudsmith host with a credential yields the raw API key as the token."""
    assert get_token(CLOUDSMITH_HOST, credential=credential) == "k_abc"


def test_get_token_accepts_a_full_https_url(credential):
    """The hostname argument may include the scheme and path."""
    url = f"https://{CLOUDSMITH_HOST}/acme/repo/"
    assert get_token(url, credential=credential) == "k_abc"


def test_get_token_uses_the_terraform_backend_kind_for_custom_domains(credential):
    """Custom-domain matching is scoped to Terraform-backed domains."""
    with patch(
        "cloudsmith_cli.credential_helpers.terraform.runtime.is_cloudsmith_domain",
        return_value=True,
    ) as mock_check:
        get_token("https://tf.acme.com/", credential=credential, org="acme")

    assert mock_check.call_args.kwargs["backend_kind"] is BackendKind.TERRAFORM
    assert mock_check.call_args.kwargs["org"] == "acme"


# ---------------------------------------------------------------------------
# 2. get_token — the "no token" paths
# ---------------------------------------------------------------------------


def test_get_token_returns_none_without_a_credential():
    """A missing credential means no token, and no exception."""
    assert get_token(CLOUDSMITH_HOST, credential=None) is None


def test_get_token_returns_none_for_a_credential_without_an_api_key():
    """An empty api_key is treated as no credential at all."""
    empty = CredentialResult(api_key="", source_name="test")
    assert get_token(CLOUDSMITH_HOST, credential=empty) is None


def test_get_token_returns_none_for_a_foreign_host(credential):
    """A non-Cloudsmith host gets no token — the helper must not leak it."""
    assert get_token(FOREIGN_HOST, credential=credential) is None


# ---------------------------------------------------------------------------
# 3. execute('get', ...) — the tuple contract
# ---------------------------------------------------------------------------


def test_execute_get_returns_token_object_for_cloudsmith_host(credential):
    """Happy path: exit-0, ``{"token": ...}`` on stdout, no stderr.

    The token is scoped to the owner/repository as ``{owner}/{repo}/{token}``.
    """
    exit_code, stdout, stderr = execute(
        "get", CLOUDSMITH_HOST, credential=credential, org="acme", repo="myrepo"
    )

    assert (exit_code, stderr) == (0, None)
    assert json.loads(stdout) == {"token": "acme/myrepo/k_abc"}


def test_execute_get_returns_empty_object_for_foreign_host(credential):
    """A non-Cloudsmith host is not ours to answer: emit ``{}`` and exit 0 so
    Terraform falls back to its own credential sources."""
    exit_code, stdout, stderr = execute("get", FOREIGN_HOST, credential=credential)

    assert (exit_code, stderr) == (0, None)
    assert json.loads(stdout) == {}


def test_execute_get_refuses_cloudsmith_host_without_credentials():
    """A Cloudsmith host we can't authenticate is a definitive failure: exit 1
    with an actionable error on stderr."""
    with patch(
        "cloudsmith_cli.credential_helpers.terraform.runtime.is_cloudsmith_domain",
        return_value=True,
    ):
        exit_code, stdout, stderr = execute(
            "get", CLOUDSMITH_HOST, credential=None, org="acme", repo="myrepo"
        )

    assert (exit_code, stdout, stderr) == (1, None, _REFUSAL_MESSAGE)


def test_execute_get_refuses_cloudsmith_host_without_an_org(credential):
    """A Cloudsmith host needs an org to build the scoped token: exit 1 with an
    actionable error on stderr, not a ``None/repo/token`` credential."""
    exit_code, stdout, stderr = execute(
        "get", CLOUDSMITH_HOST, credential=credential, org=None, repo="myrepo"
    )

    assert (exit_code, stdout, stderr) == (1, None, _MISSING_ORG_MESSAGE)


def test_execute_get_returns_empty_object_for_foreign_host_without_an_org(credential):
    """A foreign host still falls back cleanly (``{}``, exit 0) even with no org
    — the org is only required on the Cloudsmith-host path."""
    exit_code, stdout, stderr = execute(
        "get", FOREIGN_HOST, credential=credential, org=None, repo="myrepo"
    )

    assert (exit_code, stderr) == (0, None)
    assert json.loads(stdout) == {}


def test_execute_get_refuses_when_no_hostname_provided(credential):
    """An empty hostname is an error, not a traceback."""
    exit_code, stdout, stderr = execute("get", "", credential=credential)

    assert exit_code == 1
    assert stdout is None
    assert "hostname" in stderr.lower()


def test_execute_get_degrades_cleanly_on_domain_lookup_failure(credential):
    """A network/SDK error during custom-domain discovery must not raise."""
    with patch(
        "cloudsmith_cli.credential_helpers.terraform.runtime.is_cloudsmith_domain",
        side_effect=RuntimeError("boom"),
    ):
        exit_code, stdout, stderr = execute(
            "get", "https://tf.acme.com/", credential=credential, org="acme"
        )

    assert (exit_code, stdout) == (1, None)
    assert stderr == _REFUSAL_MESSAGE


# ---------------------------------------------------------------------------
# 4. execute — store / forget / unknown verbs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["store", "forget"])
def test_execute_rejects_store_and_forget(verb, credential):
    """store/forget are unsupported: there is nothing to store or forget."""
    exit_code, stdout, stderr = execute(verb, CLOUDSMITH_HOST, credential=credential)

    assert exit_code == 1
    assert stdout is None
    assert verb in stderr


def test_execute_rejects_unknown_verb(credential):
    """An unknown verb errors out per the forward-compatibility requirement."""
    exit_code, stdout, stderr = execute(
        "frobnicate", CLOUDSMITH_HOST, credential=credential
    )

    assert exit_code == 1
    assert stdout is None
    assert "Unknown verb" in stderr


# ---------------------------------------------------------------------------
# 5. CLI shim
# ---------------------------------------------------------------------------


def test_cli_prints_token_object_for_cloudsmith_host(runner):
    """The click shim resolves the credential and prints the JSON token object."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--org", "acme", "--repo", "myrepo", CLOUDSMITH_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"token": "acme/myrepo/k_abc"}


def test_cli_accepts_terraform_verb_and_hostname(runner):
    """Terraform's `get <hostname>` convention is accepted (verb + hostname).

    The on-PATH launcher forwards Terraform's arguments verbatim — including
    the `get` verb — so the command must accept the verb rather than treating
    it as an unexpected extra positional.
    """
    result = runner.invoke(
        terraform,
        args=[
            "-k",
            "k_abc",
            "--org",
            "acme",
            "--repo",
            "myrepo",
            "get",
            CLOUDSMITH_HOST,
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"token": "acme/myrepo/k_abc"}


def test_cli_rejects_store_verb(runner):
    """`store <hostname>` is answered with a non-zero exit and no token."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--repo", "myrepo", "store", CLOUDSMITH_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "k_abc" not in result.stdout


def test_cli_reads_hostname_from_stdin_when_no_argument(runner):
    """Omitting the hostname argument falls back to reading it from stdin."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--org", "acme", "--repo", "myrepo"],
        input=f"{CLOUDSMITH_HOST}\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"token": "acme/myrepo/k_abc"}


def test_cli_accepts_org_and_profile_flags(runner):
    """`--org` and `-P/--profile` are accepted and the org reaches the runtime.

    These are the options the wrapper forwards from a terraformrc `args` block,
    so they must parse on the command without requiring environment variables.
    """
    with patch(
        "cloudsmith_cli.cli.commands.credential_helper.terraform.execute",
        return_value=(0, '{"token": "k_abc"}', None),
    ) as mock_execute:
        result = runner.invoke(
            terraform,
            args=[
                "-k",
                "k_abc",
                "--repo",
                "myrepo",
                "--org=acme",
                "-P",
                "ci",
                CLOUDSMITH_HOST,
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert mock_execute.call_args.kwargs["org"] == "acme"
    assert mock_execute.call_args.kwargs["repo"] == "myrepo"


@pytest.mark.parametrize(
    "repo_flag",
    [
        ["-r", "myrepo"],
        ["--repo", "myrepo"],
        ["--repository", "myrepo"],
        ["--repo=myrepo"],
    ],
)
def test_cli_accepts_repo_flag_forms(runner, repo_flag):
    """`-r/--repo/--repository` (and the `=` form) all parse and satisfy the
    required repository option."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--org", "acme", *repo_flag, "get", CLOUDSMITH_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"token": "acme/myrepo/k_abc"}


def test_cli_repo_is_required(runner):
    """The repository is required: omitting it is a usage error, not a token.

    Terraform never tells the helper which repository is requested, so the
    command must fail fast rather than emit a credential for an unknown
    repository.
    """
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", CLOUDSMITH_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code != 0
    assert "repo" in result.output.lower()


def test_cli_org_is_required_for_a_cloudsmith_host(runner):
    """A Cloudsmith host without an org is a non-zero exit, not a token.

    The token is scoped as ``{org}/{repo}/{token}``, so an org must be
    configured (``--org``/``CLOUDSMITH_ORG``/``org`` in config.ini) before a
    credential can be emitted.
    """
    with patch(
        "cloudsmith_cli.credential_helpers.terraform.runtime.is_cloudsmith_domain",
        return_value=True,
    ):
        result = runner.invoke(
            terraform,
            args=["-k", "k_abc", "--repo", "myrepo", "get", CLOUDSMITH_HOST],
            env={"CLOUDSMITH_ORG": ""},
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    # No token must leak on stdout on the refusal path.
    assert result.stdout == ""
    assert "organisation" in result.output.lower()


def test_cli_repo_from_env_var(runner):
    """CLOUDSMITH_REPO satisfies the required repository without the flag."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--org", "acme", "get", CLOUDSMITH_HOST],
        env={"CLOUDSMITH_REPO": "envrepo"},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"token": "acme/envrepo/k_abc"}


def test_cli_prints_empty_object_for_foreign_host(runner):
    """A non-Cloudsmith host is exit-0 with ``{}`` and no leaked token."""
    result = runner.invoke(
        terraform,
        args=["-k", "k_abc", "--repo", "myrepo", FOREIGN_HOST],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {}
    assert "k_abc" not in result.stdout


def test_cli_exits_non_zero_with_a_hint_when_no_credential_resolves(runner):
    """A Cloudsmith host with no resolvable credential is exit-1 with a hint."""
    # Patch the provider chain rather than relying on env vars: a developer's
    # local ~/.cloudsmith/config.ini (or an active profile) can otherwise
    # resolve a credential and turn this into a false negative.
    with (
        patch(
            "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
            return_value=None,
        ),
        patch(
            "cloudsmith_cli.credential_helpers.terraform.runtime.is_cloudsmith_domain",
            return_value=True,
        ),
    ):
        result = runner.invoke(
            terraform,
            args=["--repo", "myrepo", CLOUDSMITH_HOST],
            env={"CLOUDSMITH_API_KEY": ""},
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    # No token must leak on stdout on the refusal path.
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# 6. Wrapper binary — delegation + verb handling
# ---------------------------------------------------------------------------


def test_wrapper_delegates_get_to_the_cli():
    """`get` execs `cloudsmith credential-helper terraform <hostname>` and
    passes its exit code straight through."""
    with patch.object(wrapper.subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        code = wrapper.main(["get", CLOUDSMITH_HOST])

    assert code == 0
    called_args = mock_run.call_args.args[0]
    assert called_args == [
        "cloudsmith",
        "credential-helper",
        "terraform",
        CLOUDSMITH_HOST,
    ]


def test_wrapper_forwards_the_cli_exit_code():
    """A non-zero exit from the CLI is propagated by the wrapper."""
    with patch.object(wrapper.subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
        code = wrapper.main(["get", CLOUDSMITH_HOST])

    assert code == 1


def test_wrapper_forwards_leading_helper_args_before_the_hostname():
    """Leading `args` from the terraformrc block are forwarded to the delegate.

    Terraform places the `args` list ahead of the verb; the wrapper passes them
    to `cloudsmith credential-helper terraform` before the hostname, so options
    like `--org` and `-P` configured in terraformrc reach the CLI.
    """
    with patch.object(wrapper.subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        code = wrapper.main(["--org=acme", "-P", "ci", "get", CLOUDSMITH_HOST])

    assert code == 0
    called_args = mock_run.call_args.args[0]
    assert called_args == [
        "cloudsmith",
        "credential-helper",
        "terraform",
        "--org=acme",
        "-P",
        "ci",
        CLOUDSMITH_HOST,
    ]


def test_wrapper_forwards_space_separated_option_values():
    """Space-separated option values (`--org acme`) forward as separate tokens.

    Terraform always appends `<verb> <hostname>` after the configured `args`,
    so the verb/hostname are the final two tokens regardless of whether options
    use the `--org=acme` or `--org acme` spelling.
    """
    with patch.object(wrapper.subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        code = wrapper.main(["--org", "acme", "-P", "ci", "get", CLOUDSMITH_HOST])

    assert code == 0
    called_args = mock_run.call_args.args[0]
    assert called_args == [
        "cloudsmith",
        "credential-helper",
        "terraform",
        "--org",
        "acme",
        "-P",
        "ci",
        CLOUDSMITH_HOST,
    ]


def test_wrapper_errors_when_cloudsmith_not_installed():
    """A missing `cloudsmith` binary is a clean error, not a traceback."""
    with patch.object(wrapper.subprocess, "run", side_effect=FileNotFoundError):
        code = wrapper.main(["get", CLOUDSMITH_HOST])

    assert code == 1


@pytest.mark.parametrize("verb", ["store", "forget"])
def test_wrapper_rejects_store_and_forget_without_delegating(verb):
    """store/forget are answered by the wrapper itself with a non-zero exit."""
    with patch.object(wrapper.subprocess, "run") as mock_run:
        code = wrapper.main([verb, CLOUDSMITH_HOST])

    assert code == 1
    mock_run.assert_not_called()


def test_wrapper_rejects_unknown_verb():
    """An unknown verb errors out without delegating."""
    with patch.object(wrapper.subprocess, "run") as mock_run:
        code = wrapper.main(["frobnicate", CLOUDSMITH_HOST])

    assert code == 1
    mock_run.assert_not_called()


def test_wrapper_errors_on_too_few_arguments():
    """Fewer than two positional arguments is a usage error."""
    assert wrapper.main([]) == 1
    assert wrapper.main(["get"]) == 1
