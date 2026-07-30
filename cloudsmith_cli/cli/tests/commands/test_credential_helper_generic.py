# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper generic` command."""

import json
from unittest.mock import patch

from ....cli.commands.credential_helper.generic import generic
from ....core.credentials.models import CredentialResult
from ....credential_helpers.generic import _REFUSAL_MESSAGE, PROTOCOL_VERSION, execute

TOKEN = "k_secret_token_value"

HERMETIC_ARGS = ["--api-key", "fake-api-key"]


def test_execute_success_returns_versioned_document():
    """A resolved credential produces the exact version-1 contract."""
    credential = CredentialResult(api_key=TOKEN, source_name="env")

    code, stdout, stderr = execute(credential=credential)

    assert code == 0
    assert stderr is None
    assert json.loads(stdout) == {
        "version": PROTOCOL_VERSION,
        "username": "token",
        "password": TOKEN,
    }


def test_execute_document_has_no_extra_keys():
    """Consumers pin on the contract - no undeclared keys may leak in."""
    credential = CredentialResult(api_key=TOKEN, source_name="env")

    _, stdout, _ = execute(credential=credential)

    assert set(json.loads(stdout)) == {"version", "username", "password"}


def test_execute_no_credential_refuses():
    """No credential -> exit 1, message on stderr, nothing on stdout."""
    code, stdout, stderr = execute(credential=None)

    assert code == 1
    assert stdout is None
    assert "Unable to retrieve credentials" in stderr


def test_execute_empty_api_key_refuses():
    """An empty api_key is not a usable credential."""
    credential = CredentialResult(api_key="", source_name="env")

    code, stdout, stderr = execute(credential=credential)

    assert code == 1
    assert stdout is None
    assert stderr == _REFUSAL_MESSAGE


def test_execute_degrades_on_unexpected_exception():
    """A raising credential degrades to a clean refusal, never a traceback."""

    class ExplodingCredential:
        """Stands in for any object whose attribute access misbehaves."""

        @property
        def api_key(self):
            raise RuntimeError("boom")

    code, stdout, stderr = execute(credential=ExplodingCredential())

    assert code == 1
    assert stdout is None
    assert stderr == _REFUSAL_MESSAGE


def test_token_only_ever_appears_on_stdout():
    """The secret must never be written to stderr."""
    credential = CredentialResult(api_key=TOKEN, source_name="env")

    _, stdout, stderr = execute(credential=credential)

    assert TOKEN in stdout
    assert stderr is None


def test_cli_emits_bare_contract_on_stdout(runner):
    """The command echoes execute()'s stdout verbatim, with nothing on stderr."""
    document = json.dumps(
        {"version": PROTOCOL_VERSION, "username": "token", "password": TOKEN}
    )

    with patch(
        "cloudsmith_cli.cli.commands.credential_helper.generic.execute",
        return_value=(0, document, None),
    ):
        result = runner.invoke(generic, args=HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "version": PROTOCOL_VERSION,
        "username": "token",
        "password": TOKEN,
    }
    assert result.stderr == ""


def test_cli_refusal_exits_1_with_empty_stdout(runner):
    """A refusal must not emit a partial document on stdout."""
    with patch(
        "cloudsmith_cli.cli.commands.credential_helper.generic.execute",
        return_value=(1, None, _REFUSAL_MESSAGE),
    ):
        result = runner.invoke(generic, args=HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Unable to retrieve credentials" in result.stderr
