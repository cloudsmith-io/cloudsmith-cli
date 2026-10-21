"""Token creation and refresh persist credentials without corrupting JSON output."""

import json
import socket
from unittest.mock import patch

import pytest

from cloudsmith_cli.cli.commands.tokens import create, refresh
from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.config import create_config_files

from .conftest import MockToken

TOKEN = MockToken("review_fake_key", "2026-01-01T00:00:00Z", "review-token")


@pytest.fixture(autouse=True)
def isolated_token_config(monkeypatch, telemetry_config_dir):
    monkeypatch.setenv("CLOUDSMITH_API_HOST", "https://api.example.com")
    monkeypatch.setenv("CLOUDSMITH_API_KEY", "review_fake_auth")
    monkeypatch.chdir(telemetry_config_dir)

    def no_network(*args, **kwargs):
        raise AssertionError("Token config tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
@pytest.mark.parametrize("existing", [False, True])
def test_create_persists_real_credentials(
    runner, telemetry_config_dir, output, existing
):
    if existing:
        (telemetry_config_dir / "config.ini").write_text("[default]\n")
        (telemetry_config_dir / "credentials.ini").write_text(
            "[default]\napi_key = review_old_key\n"
        )
    with (
        patch(
            "cloudsmith_cli.core.api.user.create_user_token_saml", return_value=TOKEN
        ),
        patch(
            "cloudsmith_cli.cli.commands.tokens.create_config_files",
            wraps=create_config_files,
        ) as save_config,
    ):
        result = runner.invoke(create, ["--save-config", "-F", output], input="y\n")
    assert result.exception is None, repr(result.exception)
    assert result.exit_code == 0
    save_config.assert_called_once()
    assert "review_fake_key" in (telemetry_config_dir / "credentials.ini").read_text()
    if output != "pretty":
        assert json.loads(result.stdout)["data"]["key"] == TOKEN.key


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
def test_401_has_no_traceback_or_writes(runner, telemetry_config_dir, output):
    with patch(
        "cloudsmith_cli.core.api.user.create_user_token_saml",
        side_effect=ApiException(status=401, detail="Not authenticated"),
    ):
        result = runner.invoke(create, ["--save-config", "-F", output])
    assert not isinstance(result.exception, AttributeError), repr(result.exception)
    assert "Not authenticated" in result.output
    assert not (telemetry_config_dir / "credentials.ini").exists()


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
def test_401_signals_failure(runner, output):
    with patch(
        "cloudsmith_cli.core.api.user.create_user_token_saml",
        side_effect=ApiException(status=401, detail="Not authenticated"),
    ):
        result = runner.invoke(create, ["--save-config", "-F", output])
    assert result.exit_code == 401
    if output != "pretty":
        assert json.loads(result.stdout)["meta"]["code"] == 401


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
def test_duplicate_declined_has_no_traceback_or_writes(
    runner, telemetry_config_dir, output
):
    with patch(
        "cloudsmith_cli.core.api.user.create_user_token_saml",
        side_effect=ApiException(
            status=400, detail="User has already created an API key"
        ),
    ):
        result = runner.invoke(create, ["--save-config", "-F", output], input="n\n")
    assert result.exception is None, repr(result.exception)
    assert result.exit_code == 0
    assert not (telemetry_config_dir / "credentials.ini").exists()
    if output != "pretty":
        assert result.stdout == ""


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
def test_duplicate_accepted_saves_and_prints_once(runner, telemetry_config_dir, output):
    with (
        patch(
            "cloudsmith_cli.core.api.user.create_user_token_saml",
            side_effect=ApiException(
                status=400, detail="User has already created an API key"
            ),
        ),
        patch("cloudsmith_cli.core.api.user.list_user_tokens", return_value=[TOKEN]),
        patch("cloudsmith_cli.core.api.user.refresh_user_token", return_value=TOKEN),
        patch(
            "cloudsmith_cli.cli.commands.tokens.create_config_files",
            wraps=create_config_files,
        ) as save_config,
    ):
        result = runner.invoke(create, ["--save-config", "--force", "-F", output])
    assert result.exception is None, repr(result.exception)
    assert result.exit_code == 0
    save_config.assert_called_once()
    assert "review_fake_key" in (telemetry_config_dir / "credentials.ini").read_text()
    if output != "pretty":
        assert json.loads(result.stdout)["data"]["key"] == TOKEN.key


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
@pytest.mark.parametrize("save", [False, True])
def test_refresh_create_fallback(runner, telemetry_config_dir, output, save):
    with (
        patch("cloudsmith_cli.core.api.user.list_user_tokens", return_value=[]),
        patch(
            "cloudsmith_cli.core.api.user.create_user_token_saml", return_value=TOKEN
        ),
    ):
        args = ["--force", "-F", output] + (["--save-config"] if save else [])
        result = runner.invoke(refresh, args)
    assert result.exception is None, repr(result.exception)
    assert result.exit_code == 0
    if output != "pretty":
        assert json.loads(result.stdout)["data"]["key"] == TOKEN.key
    if save:
        assert (telemetry_config_dir / "credentials.ini").exists(), (
            "--save-config lost on fallback"
        )
        assert TOKEN.key in (telemetry_config_dir / "credentials.ini").read_text()
    else:
        assert not (telemetry_config_dir / "credentials.ini").exists()


@pytest.mark.parametrize("output", ["pretty", "json", "pretty_json"])
def test_refresh_existing_saves_and_prints_once(runner, telemetry_config_dir, output):
    with patch("cloudsmith_cli.core.api.user.refresh_user_token", return_value=TOKEN):
        result = runner.invoke(
            refresh, [TOKEN.slug_perm, "--save-config", "--force", "-F", output]
        )
    assert result.exception is None, repr(result.exception)
    assert result.exit_code == 0
    assert "review_fake_key" in (telemetry_config_dir / "credentials.ini").read_text()
    if output != "pretty":
        assert json.loads(result.stdout)["data"]["key"] == TOKEN.key
