from unittest.mock import patch

import click
import click.testing
import pytest

from ...core import keyring as core_keyring
from ...core.api.exceptions import ApiException
from ...core.mcp.server import create_ssl_context
from ...core.session import create_requests_session
from ...core.tests.test_certificate_errors import certificate_error
from ...core.utils import get_data_path, read_file
from ..config import Options
from ..decorators import (
    common_package_action_options,
    initialise_api,
    initialise_session,
    keyring_options,
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


def test_package_action_without_skip_errors_raises_api_errors():
    @click.command()
    @common_package_action_options
    def command(**_kwargs):
        raise ApiException(status=400)

    with pytest.raises(ApiException):
        click.testing.CliRunner().invoke(command, catch_exceptions=False)


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


PROXY = "http://proxy.example.com:3128"


@pytest.mark.parametrize(
    "args,env",
    [
        (["--proxy", PROXY], {}),
        (["--api-proxy", PROXY], {}),
        ([], {"CLOUDSMITH_PROXY": PROXY, "CLOUDSMITH_API_PROXY": "http://legacy"}),
        ([], {"CLOUDSMITH_API_PROXY": PROXY}),
    ],
)
def test_proxy_and_legacy_aliases(args, env):
    @click.command()
    @initialise_session
    def command(opts):
        pass

    with patch("cloudsmith_cli.core.session.create_requests_session") as create_session:
        result = click.testing.CliRunner().invoke(command, args, env=env, obj=Options())

    assert result.exit_code == 0, result.output
    assert create_session.call_args.kwargs["proxy"] == PROXY


def test_proxy_config_key_beats_legacy_alias(telemetry_config_dir):
    path = telemetry_config_dir / "config.ini"
    path.write_text(f"[default]\nproxy={PROXY}\napi_proxy=http://legacy\n")
    opts = Options()
    opts.load_config_file(str(path))
    assert opts.proxy == PROXY


def test_proxy_reaches_sessions_without_api_configuration():
    @click.command()
    @initialise_session
    def command(opts):
        with create_requests_session() as session:
            assert session.proxies == {"http": PROXY, "https": PROXY}

    result = click.testing.CliRunner().invoke(
        command, ["--proxy", PROXY], obj=Options()
    )
    assert result.exit_code == 0, result.output


def test_initialise_session_starts_the_update_check_with_the_proxy():
    @click.command()
    @initialise_session
    def command(opts):
        pass

    with patch("cloudsmith_cli.core.update_check.start") as start:
        result = click.testing.CliRunner().invoke(
            command, ["--proxy", PROXY], obj=Options()
        )
    assert result.exit_code == 0, result.output
    assert start.call_args.args[1].proxy == PROXY


def test_nested_command_starts_the_update_check_with_its_own_proxy():
    @click.group()
    @initialise_session
    def group(opts):
        pass

    @group.command()
    @initialise_session
    def leaf(opts):
        pass

    seen = []
    with patch(
        "cloudsmith_cli.core.update_check.start",
        side_effect=lambda ctx, opts: seen.append(opts.proxy),
    ):
        result = click.testing.CliRunner().invoke(
            group, ["leaf", "--proxy", PROXY], obj=Options()
        )
    assert result.exit_code == 0, result.output
    assert seen == [PROXY]


def test_keyring_options_configure_the_keyring(monkeypatch, tmp_path):
    """The keyring settings come from the environment, with absolute paths."""

    @click.command()
    @keyring_options
    def command():
        pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("KEYRING_SUBDIR", "store")
    result = click.testing.CliRunner().invoke(
        command,
        env={
            "CLOUDSMITH_NO_KEYRING": "yes",
            "CLOUDSMITH_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "CLOUDSMITH_KEYRING_KEY": "secret",
            "CLOUDSMITH_KEYRING_FILE_PATH": "keyring.cfg",
            "CLOUDSMITH_KEYRING_DIR": "~/$KEYRING_SUBDIR",
        },
    )

    assert result.exit_code == 0, result.output
    assert core_keyring.current_settings() == core_keyring.KeyringSettings(
        no_keyring=True,
        backend="keyring.backends.null.Keyring",
        key="secret",
        file_path=str(tmp_path / "keyring.cfg"),
        directory=str(tmp_path / "home" / "store"),
    )
