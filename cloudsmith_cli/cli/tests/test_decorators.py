from unittest.mock import patch

import click
import click.testing
import pytest

from ...core.mcp.server import create_ssl_context
from ...core.session import create_requests_session
from ...core.tests.test_certificate_errors import certificate_error
from ...core.utils import get_data_path, read_file
from ..config import Options
from ..decorators import (
    initialise_api,
    initialise_session,
    report_retry,
    resolve_credentials,
)


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
    def command(opts):
        click.echo("command ran")

    return command


def test_rejected_sso_session_continues_without_early_exception():
    def reject(context):
        context.keyring_refresh_failed = True
        context.keyring_refresh_rejected = True

    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        side_effect=reject,
    ):
        result = click.testing.CliRunner().invoke(_credential_command())

    assert result.exit_code == 0
    assert "Your SAML session has expired" in result.stderr
    assert "continuing without SAML authentication" in result.stderr
    assert result.stdout == "command ran\n"


def test_failed_saml_renewal_explains_the_certificate_error():
    def fail(context):
        context.keyring_refresh_failed = True
        context.keyring_refresh_error = certificate_error(
            85, "Missing Authority Key Identifier"
        )

    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        side_effect=fail,
    ):
        result = click.testing.CliRunner().invoke(_credential_command())

    assert "has expired: " in result.stderr
    assert "Missing Authority Key Identifier" in result.stderr
    assert "Hint: The TLS certificate failed a strict X.509 check" in result.stderr
    assert result.stdout == "command ran\n"


@pytest.mark.parametrize("command_name", ["authenticate", "login"])
def test_auth_commands_skip_automatic_keyring_refresh(command_name):
    def resolve(context):
        assert context.skip_keyring_refresh is True

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


@pytest.mark.parametrize(
    "args,env,config_value,expected",
    [
        ([], {}, None, True),
        (["--without-ssl-verify-strict"], {}, None, False),
        ([], {"CLOUDSMITH_SSL_VERIFY_STRICT": "0"}, None, False),
        ([], {}, "false", False),
        (["--ssl-verify-strict"], {}, "false", True),
    ],
)
def test_without_ssl_verify_strict(
    args, env, config_value, expected, telemetry_config_dir
):
    @click.command()
    @initialise_session
    def command(opts):
        pass

    opts = Options()
    if config_value is not None:
        config_file = telemetry_config_dir / "config.ini"
        config_file.write_text(f"[default]\nssl_verify_strict={config_value}\n")
        opts.load_config_file(str(config_file))

    with patch("cloudsmith_cli.core.session.create_requests_session") as create_session:
        result = click.testing.CliRunner().invoke(command, args, env=env, obj=opts)

    assert result.exit_code == 0, result.output
    assert create_session.call_args.kwargs["ssl_verify_strict"] is expected


@pytest.mark.parametrize(
    "args,env,configured,expected",
    [
        ([], {}, False, False),
        (["--without-ssl-verify"], {}, True, False),
        (["-S"], {}, True, False),
        (
            [],
            {"CLOUDSMITH_SSL_VERIFY": "1", "CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "1"},
            False,
            True,
        ),
        (["-S"], {"CLOUDSMITH_SSL_VERIFY": "1"}, True, False),
        (["--ssl-verify", "-S"], {}, False, True),
    ],
)
def test_ssl_verify_and_legacy_cli_alias(args, env, configured, expected):
    @click.command()
    @initialise_session
    def command(opts):
        pass

    opts = Options()
    opts.ssl_verify = configured
    with patch("cloudsmith_cli.core.session.create_requests_session") as create_session:
        result = click.testing.CliRunner().invoke(command, args, env=env, obj=opts)

    assert result.exit_code == 0, result.output
    assert create_session.call_args.kwargs["ssl_verify"] is expected


@pytest.mark.parametrize(
    "body,expected",
    [
        ("api_ssl_verify=false", False),
        ("api_ssl_verify=false\nssl_verify=true", True),
    ],
)
def test_ssl_verify_config_alias(body, expected, telemetry_config_dir):
    path = telemetry_config_dir / "config.ini"
    path.write_text(f"[default]\n{body}\n")
    opts = Options()
    opts.load_config_file(str(path))
    assert opts.ssl_verify is expected


def test_profile_resets_ssl_settings(telemetry_config_dir):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\nssl_verify=false\nssl_verify_strict=false\n"
        "[profile:test]\napi_user_agent=test\n"
    )
    opts = Options()
    opts.load_config_file(None, profile="test")
    assert opts.ssl_verify is True
    assert opts.ssl_verify_strict is True


def test_default_config_keeps_api_ssl_verify_alias(telemetry_config_dir):
    (telemetry_config_dir / "config.ini").write_text(
        read_file(get_data_path(), "config.ini")
    )
    legacy_config = telemetry_config_dir / "legacy.ini"
    legacy_config.write_text("[default]\napi_ssl_verify=false\n")
    opts = Options()
    opts.load_config_file(str(legacy_config))
    assert opts.ssl_verify is False


def test_ssl_verify_reaches_all_transports():
    @click.command()
    @initialise_api
    def command(opts):
        assert opts.api_config.verify_ssl is False
        with create_requests_session() as session:
            assert session.verify is False
        assert create_ssl_context(opts.api_config) is False

    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        return_value=None,
    ):
        result = click.testing.CliRunner().invoke(command, ["--without-ssl-verify"])
    assert result.exit_code == 0, result.output
