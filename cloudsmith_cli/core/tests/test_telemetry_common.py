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


# --- Per-command policy (@telemetry.send) ------------------------------------

Send = telemetry_common.Send


def test_policy_levels_combine_as_flags():
    assert Send.ALL == Send.ERRORS | Send.USAGE
    assert Send.ERRORS in Send.ALL and Send.USAGE in Send.ALL
    assert Send.USAGE not in Send.ERRORS and Send.ERRORS not in Send.USAGE
    assert Send.ERRORS not in Send.NONE and Send.USAGE not in Send.NONE


def test_cli_module_exposes_the_four_levels():
    from cloudsmith_cli.cli import telemetry as cli_telemetry

    assert (cli_telemetry.NONE, cli_telemetry.ERRORS) == (Send.NONE, Send.ERRORS)
    assert (cli_telemetry.USAGE, cli_telemetry.ALL) == (Send.USAGE, Send.ALL)
    assert cli_telemetry.send is telemetry_common.send


def test_send_rejects_anything_but_a_policy():
    with pytest.raises(TypeError):
        telemetry_common.send("errors")  # ty: ignore[invalid-argument-type]


def _ctx(command, parent=None):
    import types

    return types.SimpleNamespace(command=command, parent=parent)


def test_send_works_above_or_below_the_click_decorator():
    import click

    @click.command()
    @telemetry_common.send(Send.ERRORS)
    def below():
        pass

    @telemetry_common.send(Send.USAGE)
    @click.command()
    def above():
        pass

    assert telemetry_common.declared_policy(below) is Send.ERRORS
    assert telemetry_common.declared_policy(above) is Send.USAGE


def test_the_policy_nearest_the_command_wins_and_all_is_the_default():
    import click

    @click.group()
    @telemetry_common.send(Send.ERRORS)
    def group():
        pass

    @group.command()
    def inherits():
        pass

    @group.command()
    @telemetry_common.send(Send.ALL)
    def overrides():
        pass

    root = _ctx(click.Group("root"))
    group_ctx = _ctx(group, root)
    assert telemetry_common.resolve_policy(_ctx(inherits, group_ctx)) is Send.ERRORS
    assert telemetry_common.resolve_policy(_ctx(overrides, group_ctx)) is Send.ALL
    assert telemetry_common.resolve_policy(root) is Send.ALL
    assert telemetry_common.resolve_policy(None) is Send.ALL
