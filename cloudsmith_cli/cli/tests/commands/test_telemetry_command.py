import json

import pytest
from click.testing import CliRunner

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.core import telemetry_common
from cloudsmith_cli.core.usage import settings


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """``status`` starts the update check like any leaf command; keep it off."""
    monkeypatch.setenv("CLOUDSMITH_NO_UPDATE_CHECK", "1")


def test_status_reports_opt_out(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(settings.KEY_ENV, "phc_testsecret")
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False and data["reason"] == "DO_NOT_TRACK"
    assert "phc_" not in result.output


def test_status_reports_log_only(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "production")
    monkeypatch.setenv(settings.MODE_ENV, "log")
    monkeypatch.delenv(settings.KEY_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False
    assert data["reason"] == "log only"


def test_status_never_prints_the_key(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "production")
    monkeypatch.setenv(settings.KEY_ENV, "phc_testsecret")
    monkeypatch.delenv(settings.MODE_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    runner = CliRunner()
    as_json = runner.invoke(main, ["telemetry", "status", "-F", "json"])
    assert as_json.exit_code == 0
    data = json.loads(as_json.output)["data"]
    assert data["enabled"] is True and data["reason"] == "enabled"
    assert "phc_testsecret" not in as_json.output
    as_text = runner.invoke(main, ["telemetry", "status"])
    assert as_text.exit_code == 0
    assert "Usage telemetry: on (enabled)" in as_text.output
    assert "phc_testsecret" not in as_text.output


def test_status_reports_non_cloudsmith_host(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    result = CliRunner().invoke(
        main,
        [
            "telemetry",
            "status",
            "-F",
            "json",
            "--api-host",
            "https://packages.example.com",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False
    assert data["reason"] == "non-Cloudsmith API host"


def test_status_reports_ssl_off_from_env_like_the_gate(
    monkeypatch, telemetry_config_dir
):  # pylint: disable=unused-argument
    # The run gate treats a falsy CLOUDSMITH_SSL_VERIFY as off even when
    # --ssl-verify is typed, so status must say off too.
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.setenv("CLOUDSMITH_SSL_VERIFY", "false")
    result = CliRunner().invoke(
        main, ["telemetry", "status", "-F", "json", "--ssl-verify"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False
    assert data["reason"] == "SSL verification off"


@pytest.mark.parametrize("ssl_off", ["-S", "--without-api-ssl-verify"])
def test_status_reports_a_typed_ssl_off_flag_like_the_gate(
    monkeypatch, telemetry_config_dir, ssl_off
):  # pylint: disable=unused-argument
    # `--ssl-verify -S`: the command resolves verification on, but the run
    # gate sees the typed -S and sends nothing, so status must say off.
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "production")
    monkeypatch.setenv(settings.KEY_ENV, "phc_test")
    monkeypatch.delenv(settings.MODE_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSMITH_SSL_VERIFY", raising=False)
    monkeypatch.delenv("CLOUDSMITH_WITHOUT_API_SSL_VERIFY", raising=False)
    result = CliRunner().invoke(
        main, ["telemetry", "status", "-F", "json", "--ssl-verify", ssl_off]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False
    assert data["reason"] == "SSL verification off"


def test_status_reports_development_build(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "development")
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    monkeypatch.delenv(settings.KEY_ENV, raising=False)
    monkeypatch.delenv(settings.HOST_ENV, raising=False)
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["enabled"] is False
    assert data["reason"] == "development build"


def test_id_and_reset(monkeypatch, usage_state_dir):
    from cloudsmith_cli.core.usage import identity

    created = identity.resolve(ephemeral=False, install_id_enabled=True).distinct_id
    runner = CliRunner()
    shown = json.loads(runner.invoke(main, ["telemetry", "id", "-F", "json"]).output)[
        "data"
    ]
    assert shown["install_id"] == created
    reset = json.loads(
        runner.invoke(main, ["telemetry", "reset", "-F", "json"]).output
    )["data"]
    assert reset == {"deleted": True}
    shown = json.loads(runner.invoke(main, ["telemetry", "id", "-F", "json"]).output)[
        "data"
    ]
    assert shown["install_id"] is None


def test_reset_failure_exits_non_zero(monkeypatch, usage_state_dir):
    from cloudsmith_cli.core.usage import identity

    def fail():
        raise identity.IdentityResetError("could not remove the stored install ID")

    monkeypatch.setattr(identity, "reset", fail)
    result = CliRunner().invoke(main, ["telemetry", "reset"])
    assert result.exit_code == 1
    assert "could not remove the stored install ID" in result.output


@pytest.mark.parametrize("via_env", [False, True])
def test_status_reports_a_config_file_opt_out(
    monkeypatch, telemetry_config_dir, tmp_path, via_env
):  # pylint: disable=unused-argument
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    path = tmp_path / "optout.ini"
    path.write_text("[default]\ntelemetry = false\n")
    args = ["telemetry", "status", "-F", "json"]
    if via_env:
        monkeypatch.setenv(telemetry_common.CONFIG_FILE_ENV, str(path))
    else:
        args += ["--config-file", str(path)]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["reason"] == "config"
