from unittest.mock import patch

import click
import click.testing
import pytest

from ..decorators import report_retry, resolve_credentials


def test_report_retry_writes_to_stderr():
    @click.command()
    def command():
        click.echo('{"data": []}')
        report_retry(30, context="retry-after")

    result = click.testing.CliRunner().invoke(command, catch_exceptions=False)

    assert result.stdout == '{"data": []}\n'
    assert "Request was throttled (429)" in result.stderr


def _credential_command(name="example"):
    @click.command(name=name)
    @resolve_credentials
    @click.pass_context
    def command(ctx, opts):
        click.echo("command ran")

    return command


def test_rejected_sso_session_continues_without_early_exception():
    def reject(context):
        context.keyring_refresh_failed = True
        context.keyring_refresh_rejected = True
        return None

    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        side_effect=reject,
    ):
        result = click.testing.CliRunner().invoke(_credential_command())

    assert result.exit_code == 0
    assert "Your SSO session has expired" in result.stderr
    assert "continuing without SSO authentication" in result.stderr
    assert result.stdout == "command ran\n"


@pytest.mark.parametrize("command_name", ["authenticate", "login"])
def test_auth_commands_skip_automatic_keyring_refresh(command_name):
    def resolve(context):
        assert context.skip_keyring_refresh is True
        return None

    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        side_effect=resolve,
    ):
        result = click.testing.CliRunner().invoke(
            _credential_command(name=command_name)
        )

    assert result.exit_code == 0
    assert result.stdout == "command ran\n"
    assert result.stderr == ""
