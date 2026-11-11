import json

import pytest
from click.testing import CliRunner

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.core import telemetry, telemetry_common
from cloudsmith_cli.core.usage import settings

#: Never contacted: status only checks that a DSN is set.
FAKE_DSN = "https://publickey@o0.ingest.sentry.invalid/0"


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """``status`` starts the update check like any leaf command; keep it off."""
    monkeypatch.setenv("CLOUDSMITH_NO_UPDATE_CHECK", "1")


def test_status_reports_opt_out(monkeypatch):
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(settings.KEY_ENV, "phc_testsecret")
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert (
        data["usage_reporting"]["status"] == "disabled"
        and data["usage_reporting"]["reason"] == "DO_NOT_TRACK"
    )
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
    assert data["usage_reporting"]["status"] == "log"
    assert data["usage_reporting"]["reason"] == "CLOUDSMITH_TELEMETRY"


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
    assert (
        data["usage_reporting"]["status"] == "enabled"
        and data["usage_reporting"]["reason"] == "default"
    )
    assert "phc_testsecret" not in as_json.output
    as_text = runner.invoke(main, ["telemetry", "status"])
    assert as_text.exit_code == 0
    assert "Usage reporting: enabled (default)" in as_text.output
    assert "phc_testsecret" not in as_text.output


@pytest.fixture()
def production_with_key(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "production")
    monkeypatch.setenv(settings.KEY_ENV, "phc_test")
    for name in (*telemetry_common.MODE_ENVS, *telemetry_common.OPT_OUT_ENVS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSMITH_SSL_VERIFY", raising=False)
    # The suite empties the DSN so that nothing is reported.
    monkeypatch.setenv(telemetry.DSN_ENV, FAKE_DSN)


def _status(*args):
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["data"], result.stderr


@pytest.mark.parametrize("value", ["enable", "Enabled", " on ", "true", "1", "yes"])
def test_status_enable_wins_over_the_opt_outs(production_with_key, monkeypatch, value):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(telemetry_common.NO_TELEMETRY_ENV, "1")
    monkeypatch.setenv(settings.MODE_ENV, value)
    data, _ = _status()
    assert (
        data["usage_reporting"]["status"] == "enabled"
        and data["usage_reporting"]["reason"] == "CLOUDSMITH_TELEMETRY"
    )


@pytest.mark.parametrize("value", ["disable", "DISABLED", "off", "false", "0", "no"])
def test_status_disable(production_with_key, monkeypatch, value):
    monkeypatch.setenv(settings.MODE_ENV, value)
    data, _ = _status()
    assert (
        data["usage_reporting"]["status"] == "disabled"
        and data["usage_reporting"]["reason"] == "CLOUDSMITH_TELEMETRY"
    )


def test_status_no_telemetry_wins_over_do_not_track(production_with_key, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(telemetry_common.NO_TELEMETRY_ENV, "1")
    data, _ = _status()
    assert data["usage_reporting"]["status"] == "disabled"
    assert data["usage_reporting"]["reason"] == telemetry_common.NO_TELEMETRY_ENV


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_status_a_false_no_telemetry_cannot_override_do_not_track(
    production_with_key, monkeypatch, value
):
    monkeypatch.setenv(telemetry_common.NO_TELEMETRY_ENV, value)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    data, _ = _status()
    assert (
        data["usage_reporting"]["status"] == "disabled"
        and data["usage_reporting"]["reason"] == "DO_NOT_TRACK"
    )


def test_status_env_wins_over_config(
    production_with_key, telemetry_config_dir, monkeypatch
):
    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = false\n")
    assert _status()[0]["usage_reporting"]["reason"] == "telemetry in config.ini"
    monkeypatch.setenv(settings.MODE_ENV, "enable")
    data, _ = _status()
    assert (
        data["usage_reporting"]["status"] == "enabled"
        and data["usage_reporting"]["reason"] == "CLOUDSMITH_TELEMETRY"
    )


def test_status_unrecognised_value_warns_and_falls_back(
    production_with_key, monkeypatch
):
    monkeypatch.setenv(settings.MODE_ENV, "nope")
    data, stderr = _status()
    assert (
        data["usage_reporting"]["status"] == "enabled"
        and data["usage_reporting"]["reason"] == "default"
    )
    assert "`CLOUDSMITH_TELEMETRY` is not recognised" in stderr
    assert "nope" not in stderr
    # Falls through to the next setting, not straight to the default.
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    data, _ = _status()
    assert (
        data["usage_reporting"]["status"] == "disabled"
        and data["usage_reporting"]["reason"] == "DO_NOT_TRACK"
    )


def test_status_unrecognised_install_id_value_warns_and_keeps_the_default(
    production_with_key, monkeypatch
):
    monkeypatch.setenv(settings.INSTALL_ID_ENV, "nope")
    data, stderr = _status()
    assert data["install_id_enabled"] is True
    assert "`CLOUDSMITH_TELEMETRY_INSTALL_ID` is not recognised" in stderr
    assert stderr.count("Warning:") == 1


def test_status_recognised_values_do_not_warn(production_with_key, monkeypatch):
    monkeypatch.setenv(settings.MODE_ENV, "log")
    monkeypatch.setenv(settings.INSTALL_ID_ENV, "disable")
    data, stderr = _status()
    assert (
        data["usage_reporting"]["status"] == "log"
        and data["install_id_enabled"] is False
    )
    assert "Warning:" not in stderr


def test_status_usage_off_errors_on(production_with_key, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(telemetry_common.ERROR_REPORTING_ENV, "enable")
    result = CliRunner().invoke(main, ["telemetry", "status"])
    assert result.exit_code == 0, result.output
    assert "Usage reporting: disabled (DO_NOT_TRACK)" in result.output
    assert (
        "Error reporting: enabled (CLOUDSMITH_TELEMETRY_ERROR_REPORTING)"
        in result.output
    )


def test_status_each_kind_reports_its_own_mode(production_with_key, monkeypatch):
    monkeypatch.setenv(settings.MODE_ENV, "log")
    monkeypatch.setenv(telemetry_common.USAGE_REPORTING_ENV, "disable")
    data, stderr = _status()
    assert data["usage_reporting"] == {
        "status": "disabled",
        "reason": "CLOUDSMITH_TELEMETRY_USAGE_REPORTING",
        "endpoint": settings.host(),
    }
    assert data["error_reporting"] == {
        "status": "log",
        "reason": "CLOUDSMITH_TELEMETRY",
    }
    assert "Warning:" not in stderr


def test_status_error_reporting_without_a_dsn(production_with_key, monkeypatch):
    monkeypatch.setenv(telemetry.DSN_ENV, "")
    assert _status()[0]["error_reporting"]["reason"] == "no DSN"
    # Log mode prints the report and needs no DSN.
    monkeypatch.setenv(telemetry_common.ERROR_REPORTING_ENV, "log")
    assert _status()[0]["error_reporting"]["status"] == "log"


def test_status_error_reporting_ignores_the_usage_gates(
    production_with_key, monkeypatch
):
    data, _ = _status("--api-host", "https://packages.example.com")
    assert data["usage_reporting"]["reason"] == "non-Cloudsmith API host"
    assert data["error_reporting"] == {"status": "enabled", "reason": "default"}


def test_status_config_keys_per_kind(
    production_with_key, telemetry_config_dir, monkeypatch
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\ntelemetry = disable\ntelemetry_error_reporting = enable\n"
    )
    data, _ = _status()
    assert data["usage_reporting"]["reason"] == "telemetry in config.ini"
    assert data["error_reporting"] == {
        "status": "enabled",
        "reason": "telemetry_error_reporting in config.ini",
    }


@pytest.mark.parametrize(
    "name", [telemetry_common.USAGE_REPORTING_ENV, telemetry_common.ERROR_REPORTING_ENV]
)
def test_status_unrecognised_kind_variable_warns(
    production_with_key, monkeypatch, name
):
    monkeypatch.setenv(name, "nope")
    _, stderr = _status()
    assert f"`{name}` is not recognised" in stderr
    assert "`enable`, `disable`, or `log`" in stderr


@pytest.mark.parametrize("key", telemetry_common.CONFIG_KEYS)
def test_status_unrecognised_config_value_warns_and_falls_back(
    production_with_key, telemetry_config_dir, key
):
    (telemetry_config_dir / "config.ini").write_text(f"[default]\n{key} = nope\n")
    data, stderr = _status()
    assert f"The value of the `{key}` key in config.ini is not recognised" in stderr
    assert "nope" not in stderr
    assert data["usage_reporting"]["status"] == "enabled"


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
    assert data["usage_reporting"]["status"] == "disabled"
    assert data["usage_reporting"]["reason"] == "non-Cloudsmith API host"


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
    assert data["usage_reporting"]["status"] == "disabled"
    assert data["usage_reporting"]["reason"] == "SSL verification off"


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
    # The deprecated spelling also prints a warning, on stderr.
    data = json.loads(result.stdout)["data"]
    assert data["usage_reporting"]["status"] == "disabled"
    assert data["usage_reporting"]["reason"] == "SSL verification off"


def test_status_reports_development_build(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    monkeypatch.setattr(telemetry_common, "get_environment", lambda: "development")
    monkeypatch.delenv(telemetry_common.DO_NOT_TRACK_ENV, raising=False)
    monkeypatch.delenv(telemetry_common.NO_TELEMETRY_ENV, raising=False)
    monkeypatch.delenv(settings.KEY_ENV, raising=False)
    monkeypatch.delenv(settings.HOST_ENV, raising=False)
    result = CliRunner().invoke(main, ["telemetry", "status", "-F", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)["data"]
    assert data["usage_reporting"]["status"] == "disabled"
    assert data["usage_reporting"]["reason"] == "development build"


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
    assert (
        json.loads(result.output)["data"]["usage_reporting"]["reason"]
        == "telemetry in config.ini"
    )
