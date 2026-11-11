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


Mode = telemetry_common.Mode
Kind = telemetry_common.Kind
TELEMETRY = telemetry_common.MODE_ENV
USAGE = telemetry_common.USAGE_REPORTING_ENV
ERRORS = telemetry_common.ERROR_REPORTING_ENV
NO_TELEMETRY = telemetry_common.NO_TELEMETRY_ENV
DNT = telemetry_common.DO_NOT_TRACK_ENV


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, (None, None)),
        ({TELEMETRY: ""}, (None, None)),
        ({TELEMETRY: "  "}, (None, None)),
        ({TELEMETRY: "enable"}, (Mode.ENABLED, TELEMETRY)),
        ({TELEMETRY: " ENABLED "}, (Mode.ENABLED, TELEMETRY)),
        ({TELEMETRY: "on"}, (Mode.ENABLED, TELEMETRY)),
        ({TELEMETRY: "1"}, (Mode.ENABLED, TELEMETRY)),
        ({TELEMETRY: "disable"}, (Mode.DISABLED, TELEMETRY)),
        ({TELEMETRY: "off"}, (Mode.DISABLED, TELEMETRY)),
        ({TELEMETRY: "0"}, (Mode.DISABLED, TELEMETRY)),
        ({TELEMETRY: "LOG"}, (Mode.LOG, TELEMETRY)),
        # CLOUDSMITH_TELEMETRY wins over both opt-outs, whatever it says.
        ({TELEMETRY: "enable", NO_TELEMETRY: "1", DNT: "1"}, (Mode.ENABLED, TELEMETRY)),
        ({TELEMETRY: "log", DNT: "1"}, (Mode.LOG, TELEMETRY)),
        # Then CLOUDSMITH_NO_TELEMETRY, then DO_NOT_TRACK.
        ({NO_TELEMETRY: "1", DNT: "1"}, (Mode.DISABLED, NO_TELEMETRY)),
        ({DNT: "true"}, (Mode.DISABLED, DNT)),
        # A false opt-out is not a setting, so it cannot override the next one.
        ({NO_TELEMETRY: "0", DNT: "1"}, (Mode.DISABLED, DNT)),
        ({NO_TELEMETRY: "false"}, (None, None)),
        # An unrecognised value is ignored: the next setting decides.
        ({TELEMETRY: "nope", DNT: "1"}, (Mode.DISABLED, DNT)),
        ({TELEMETRY: "nope"}, (None, None)),
    ],
)
def test_env_mode_precedence(kind, env, expected):
    assert telemetry_common.env_mode(kind, env) == expected


@pytest.mark.parametrize(
    "env,usage,errors",
    [
        # Each kind's own variable wins over everything else, for that kind only.
        ({USAGE: "disable"}, (Mode.DISABLED, USAGE), (None, None)),
        ({ERRORS: "log"}, (None, None), (Mode.LOG, ERRORS)),
        (
            {USAGE: "disable", TELEMETRY: "enable"},
            (Mode.DISABLED, USAGE),
            (Mode.ENABLED, TELEMETRY),
        ),
        (
            {ERRORS: "enable", DNT: "1"},
            (Mode.DISABLED, DNT),
            (Mode.ENABLED, ERRORS),
        ),
        (
            {ERRORS: "enable", NO_TELEMETRY: "1", TELEMETRY: "disable"},
            (Mode.DISABLED, TELEMETRY),
            (Mode.ENABLED, ERRORS),
        ),
        # An unrecognised value falls through to CLOUDSMITH_TELEMETRY.
        (
            {USAGE: "nope", TELEMETRY: "log"},
            (Mode.LOG, TELEMETRY),
            (Mode.LOG, TELEMETRY),
        ),
    ],
)
def test_each_kind_has_its_own_variable(env, usage, errors):
    assert telemetry_common.env_mode(Kind.USAGE, env) == usage
    assert telemetry_common.env_mode(Kind.ERRORS, env) == errors


@pytest.mark.parametrize(
    "name,value,expected",
    [
        (TELEMETRY, "nope", True),
        (TELEMETRY, "log", False),
        (TELEMETRY, "", False),
        (TELEMETRY, "Disabled", False),
        (USAGE, "log", False),
        (USAGE, "nope", True),
        (ERRORS, "off", False),
        (ERRORS, "maybe", True),
        (telemetry_common.INSTALL_ID_ENV, "log", True),
        (telemetry_common.INSTALL_ID_ENV, "off", False),
        (telemetry_common.INSTALL_ID_ENV, " ", False),
    ],
)
def test_unrecognised(name, value, expected):
    assert telemetry_common.unrecognised(name, {name: value}) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("log", Mode.LOG),
        (" Disable ", Mode.DISABLED),
        ("yes", Mode.ENABLED),
        (False, Mode.DISABLED),
        (True, Mode.ENABLED),
        ("nope", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_mode(value, expected):
    assert telemetry_common.parse_mode(value) is expected


def _reader(calls, **keys):
    from types import SimpleNamespace

    def read():
        calls.append(keys)
        return SimpleNamespace(**keys)

    return read


@pytest.fixture()
def no_env(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    from cloudsmith_cli.cli import config

    monkeypatch.delattr(config.OPTIONS, "value", raising=False)
    for name in (*telemetry_common.MODE_ENVS, NO_TELEMETRY, DNT):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "keys,usage,errors",
    [
        ({}, None, None),
        ({"telemetry": "disable"}, "telemetry", "telemetry"),
        ({"telemetry": "nope"}, None, None),
        (
            {"telemetry": "disable", "telemetry_error_reporting": "enable"},
            "telemetry",
            "telemetry_error_reporting",
        ),
        (
            {"telemetry_usage_reporting": "log", "telemetry": "enable"},
            "telemetry_usage_reporting",
            "telemetry",
        ),
    ],
)
def test_config_mode_specific_key_wins(no_env, keys, usage, errors):
    for kind, key in ((Kind.USAGE, usage), (Kind.ERRORS, errors)):
        _, source = telemetry_common.config_mode(kind, _reader([], **keys))
        assert source == (f"{key} in config.ini" if key else None)


def test_config_mode_fails_closed(no_env):
    def unreadable():
        raise OSError("unreadable")

    assert telemetry_common.config_mode(Kind.USAGE, unreadable) == (
        Mode.DISABLED,
        telemetry_common.CONFIG_UNREADABLE,
    )


def test_config_mode_loaded_options_opt_out_wins(no_env, monkeypatch):
    from cloudsmith_cli.cli import config

    opts = config.Options()
    opts.telemetry_usage_reporting = "disable"
    monkeypatch.setattr(config.OPTIONS, "value", opts, raising=False)
    calls = []
    reader = _reader(calls, telemetry="enable")
    assert telemetry_common.config_mode(Kind.USAGE, reader)[0] is Mode.DISABLED
    assert calls == []
    # The other kind is not affected, and the fresh read still counts.
    assert telemetry_common.config_mode(Kind.ERRORS, reader)[0] is Mode.ENABLED


def test_resolve_mode_reads_config_only_when_no_env_var_decides(no_env, monkeypatch):
    calls = []
    off = _reader(calls, telemetry="false")
    assert telemetry_common.resolve_mode(Kind.USAGE, off) == (
        Mode.DISABLED,
        "telemetry in config.ini",
    )
    assert telemetry_common.resolve_mode(Kind.USAGE, _reader(calls)) == (
        Mode.ENABLED,
        "default",
    )
    assert len(calls) == 2
    # The env vars win over config.ini, which is then not read at all.
    monkeypatch.setenv(DNT, "1")
    assert telemetry_common.resolve_mode(Kind.USAGE, off) == (Mode.DISABLED, DNT)
    monkeypatch.setenv(USAGE, "enable")
    on = _reader(calls, telemetry_usage_reporting="disable")
    assert telemetry_common.resolve_mode(Kind.USAGE, on) == (Mode.ENABLED, USAGE)
    assert len(calls) == 2


def test_sentry_module_reexports_shared_names():
    assert telemetry.resolve_mode is telemetry_common.resolve_mode
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
    assert telemetry_common.read_config_file().telemetry == "false"
    # The CLI's own reader is left as it was for the rest of the run.
    assert config.ConfigReader.config_files == files
    assert config.ConfigReader.config_searchpath == searchpath

    monkeypatch.delenv(telemetry_common.CONFIG_FILE_ENV)
    assert telemetry_common.read_config_file().telemetry == "true"


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
