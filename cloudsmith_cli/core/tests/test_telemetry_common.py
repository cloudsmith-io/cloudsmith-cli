"""Tests for the helpers shared by error reporting, update checks and usage."""

import pytest

from cloudsmith_cli.core import telemetry, telemetry_common


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://api.cloudsmith.io", True),
        ("https://api.cloudsmith.com/v1/", True),
        ("api.cloudsmith.io", True),
        ("https://cloudsmith.io", True),
        ("https://evilcloudsmith.io", False),
        ("https://cloudsmith.io.evil.com", False),
        ("https://artifacts.example.com", False),
        ("", True),
        (None, True),
    ],
)
def test_is_cloudsmith_host(value, expected):
    # Empty or missing means the default host, which is Cloudsmith's.
    assert telemetry_common.is_cloudsmith_host(value) is expected


def test_sentry_module_reexports_shared_names():
    assert telemetry.telemetry_disabled is telemetry_common.telemetry_disabled
    assert telemetry.config_disabled is telemetry_common.config_disabled
    assert telemetry.get_environment is telemetry_common.get_environment
    assert telemetry.OPT_OUT_ENVS == telemetry_common.OPT_OUT_ENVS


def test_wait_budget_is_shared_and_never_negative():
    budget = telemetry_common.WaitBudget.shared()
    budget.reset(1.0)
    budget.spend(0.4)
    assert telemetry_common.WaitBudget.shared().remaining() == pytest.approx(0.6)
    budget.spend(5.0)
    assert budget.remaining() == 0.0


def test_read_config_file_honours_the_config_file_env(
    telemetry_config_dir, tmp_path, monkeypatch
):
    from cloudsmith_cli.cli import config

    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = true\n")
    path = tmp_path / "optout.ini"
    path.write_text("[default]\ntelemetry = false\n")
    files = list(config.ConfigReader.config_files)
    searchpath = list(config.ConfigReader.config_searchpath)

    monkeypatch.setenv(telemetry_common.CONFIG_FILE_ENV, str(path))
    assert telemetry_common.read_config_file().telemetry is False
    # The CLI's own reader is left as it was for the rest of the run.
    assert config.ConfigReader.config_files == files
    assert config.ConfigReader.config_searchpath == searchpath

    monkeypatch.delenv(telemetry_common.CONFIG_FILE_ENV)
    assert telemetry_common.read_config_file().telemetry is True


def test_config_file_env_matches_the_option_declaration():
    from cloudsmith_cli.cli.commands import main

    envvars = {p.name: p.envvar for p in main.main.params}
    assert envvars["config_file"] == telemetry_common.CONFIG_FILE_ENV
