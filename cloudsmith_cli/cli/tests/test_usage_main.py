import json

import pytest

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.core.usage import notice, state


@pytest.fixture()
def notice_seen():
    state.write({"notice_version": notice.NOTICE_VERSION})


def test_version_sends_success(usage_events, notice_seen):
    assert main(args=["--version"], standalone_mode=False) in (0, None)
    assert usage_events[-1]["properties"]["outcome"] == "success"
    assert usage_events[-1]["properties"]["command"] == "<root>"


def test_run_without_agent_markers_is_human(usage_events, notice_seen):
    main(args=["--version"], standalone_mode=False)
    props = usage_events[-1]["properties"]
    assert props["persona"] == "human" and "agent" not in props


def test_agent_run_sends_a_name_never_the_raw_value(
    usage_events, notice_seen, monkeypatch
):
    monkeypatch.setenv("AI_AGENT", "acme-internal-bot_9")
    main(args=["--version"], standalone_mode=False)
    props = usage_events[-1]["properties"]
    assert props["persona"] == "agent"
    assert props["agent"] == "unidentified_agent"
    assert "acme" not in json.dumps(usage_events[-1])


def test_help_is_recorded_as_help(usage_events, notice_seen):
    # Click returns 0 for --help when standalone_mode is False.
    assert main(args=["repositories", "--help"], standalone_mode=False) == 0
    props = usage_events[-1]["properties"]
    assert props["outcome"] == "help" and props["command"] == "repositories"


def test_usage_error_keeps_exit_code(usage_events, notice_seen):
    with pytest.raises(SystemExit) as exit_info:
        main(args=["repositories", "--no-such-flag"])
    assert exit_info.value.code == 2
    assert usage_events[-1]["properties"]["outcome"] == "usage_error"


def test_credential_helper_sends_nothing(usage_events, notice_seen):
    with pytest.raises(SystemExit):
        main(args=["credential-helper", "docker", "list"])
    assert usage_events == []


def test_finish_failure_does_not_change_exit(usage_events, notice_seen, monkeypatch):
    from cloudsmith_cli.core.usage import run

    monkeypatch.setattr(run, "_finish", lambda facts: 1 / 0)
    assert main(args=["--version"], standalone_mode=False) in (0, None)


@pytest.mark.parametrize(
    "env, args",
    [
        ({"CLOUDSMITH_API_HOST": "https://artifacts.example.com"}, ["--version"]),
        ({"CLOUDSMITH_SSL_VERIFY": "false"}, ["--version"]),
        ({"CLOUDSMITH_SSL_VERIFY": "Off"}, ["--version"]),
        ({"CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "1"}, ["--version"]),
        ({}, ["list", "repos", "--api-host", "https://artifacts.example.com", "-h"]),
        (
            {},
            ["list", "repos", "--api-host", "https://artifacts.example.com", "--help"],
        ),
        ({}, ["list", "repos", "--without-ssl-verify", "--help"]),
        ({}, ["list", "repos", "-S", "--help"]),
    ],
)
def test_host_and_ssl_gates_hold_before_session_setup(
    usage_events, notice_seen, monkeypatch, env, args
):
    # None of these runs reaches initialise_session, which is where the
    # options normally land in opts.
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert main(args=args, standalone_mode=False) in (0, None)
    assert usage_events == []


def test_cloudsmith_api_host_from_env_still_sends(
    usage_events, notice_seen, monkeypatch
):
    monkeypatch.setenv("CLOUDSMITH_API_HOST", "https://api.cloudsmith.io")
    monkeypatch.setenv("CLOUDSMITH_SSL_VERIFY", "true")
    assert main(args=["--version"], standalone_mode=False) in (0, None)
    assert len(usage_events) == 1


def test_empty_ssl_env_does_not_turn_ssl_off(usage_events, notice_seen, monkeypatch):
    # Click treats an empty env var as unset.
    monkeypatch.setenv("CLOUDSMITH_SSL_VERIFY", "")
    monkeypatch.setenv("CLOUDSMITH_WITHOUT_API_SSL_VERIFY", "")
    assert main(args=["--version"], standalone_mode=False) in (0, None)
    assert len(usage_events) == 1


@pytest.mark.parametrize(
    "instruction, env",
    [
        ("zsh_source", {}),
        ("bash_complete", {"COMP_WORDS": "cloudsmith ", "COMP_CWORD": "1"}),
    ],
)
def test_shell_completion_sends_nothing(
    usage_events, notice_seen, monkeypatch, capsys, instruction, env
):
    monkeypatch.setenv("_CLOUDSMITH_COMPLETE", instruction)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as exit_info:
        main(args=[], prog_name="cloudsmith")
    assert exit_info.value.code == 0
    assert capsys.readouterr().out  # the script or the completions
    assert usage_events == []


@pytest.fixture()
def reporting_enabled(sentry_events, monkeypatch):  # pylint: disable=unused-argument
    """Every opt-out cleared, as error reporting tests do (no usage_events)."""
    for name in (
        "CLOUDSMITH_API_HOST",
        "CLOUDSMITH_SSL_VERIFY",
        "CLOUDSMITH_WITHOUT_API_SSL_VERIFY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUDSMITH_NO_UPDATE_CHECK", "1")


def test_exported_key_never_reaches_tests(
    reporting_enabled, notice_seen, blocked_usage_posts
):
    # Discriminates when CLOUDSMITH_TELEMETRY_POSTHOG_KEY is exported: the
    # autouse guard removes it, so the run stops before any POST.
    assert main(args=["--version"], standalone_mode=False) in (0, None)
    assert blocked_usage_posts == []


def test_a_test_that_sets_the_key_still_posts_nothing(
    reporting_enabled, notice_seen, monkeypatch, blocked_usage_posts
):
    from cloudsmith_cli.core.usage import settings

    monkeypatch.setenv(settings.KEY_ENV, "phc_test")
    assert main(args=["--version"], standalone_mode=False) in (0, None)
    # The run reached the POST, and the guard took it instead of the network.
    assert len(blocked_usage_posts) == 1
    blocked_usage_posts.clear()  # expected: don't fail at teardown


def test_guarded_post_raises(blocked_usage_posts):
    from cloudsmith_cli.core.usage import sender

    with pytest.raises(AssertionError, match="must not send usage telemetry"):
        sender._post(None, "https://eu.i.posthog.com/i/v0/e/", "{}", 1.0)
    assert len(blocked_usage_posts) == 1
    blocked_usage_posts.clear()


@pytest.fixture()
def no_repos_api(monkeypatch):
    """Answer ``list repos`` with an empty page instead of calling the API."""
    from cloudsmith_cli.core.api import repos
    from cloudsmith_cli.core.pagination import PageInfo

    calls = []

    def list_repos(**kwargs):
        calls.append(kwargs)
        return [], PageInfo()

    monkeypatch.setattr(repos, "list_repos", list_repos)
    return calls


INSTALL_ID = "5b0d9c1e-6a2f-4d0e-9b7a-3f1c2e8d4a10"


def test_install_id_never_reaches_sentry(
    usage_events, sentry_events, notice_seen, monkeypatch
):
    from cloudsmith_cli.core.api import repos

    state.write({"install_id": INSTALL_ID, "created_at": 1792076242})

    def crash(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(repos, "list_repos", crash)
    with pytest.raises(SystemExit) as exit_info:
        main(args=["list", "repos", "acme/x"])
    assert exit_info.value.code == 1

    # One run produced both: the usage event carries the ID, the error does not.
    assert usage_events[-1]["distinct_id"] == INSTALL_ID
    assert usage_events[-1]["properties"]["outcome"] == "unexpected_error"
    (error,) = sentry_events
    serialised = json.dumps(error)
    assert INSTALL_ID not in serialised
    assert "1792076242" not in serialised
    assert "install_id" not in serialised


@pytest.mark.parametrize(
    "host, sent",
    [("https://api.cloudsmith.io", 1), ("https://artifacts.example.com", 0)],
)
def test_forwarding_command_resolves_a_typed_api_host(
    usage_events, notice_seen, no_repos_api, host, sent
):
    # `list repos` hands off to `repositories get` (ctx.forward), whose
    # session setup runs in a sub-context of the leaf.
    args = ["list", "repos", "acme/x", "-F", "json", "--api-host", host]
    assert main(args=args, standalone_mode=False) in (0, None)
    assert len(no_repos_api) == 1  # the run reached the session and the API
    assert len(usage_events) == sent


def _run_root(args):
    """Run ``main()`` on a root path that ends before config is loaded."""
    from cloudsmith_cli.cli import config

    if args == ["--help"]:
        assert main(args=args, standalone_mode=False) == 0
    else:
        with pytest.raises(SystemExit) as exit_info:
            main(args=args)
        assert exit_info.value.code == 2
    # Root --help exits at parse and root usage errors in resolve_command,
    # both before the root callback loads config.
    assert getattr(config.OPTIONS, "value", None) is None


@pytest.mark.parametrize("args", [["--help"], ["no-such-command"]])
@pytest.mark.parametrize(
    "setting",
    [
        "api_host = https://artifacts.example.com",
        "ssl_verify = false",
        "api_ssl_verify = false",
    ],
)
def test_config_file_host_and_ssl_gates_hold_before_config_loads(
    usage_events, notice_seen, telemetry_config_dir, args, setting
):
    (telemetry_config_dir / "config.ini").write_text(f"[default]\n{setting}\n")
    _run_root(args)
    assert usage_events == []


def test_config_file_profile_host_gate_holds_before_config_loads(
    usage_events, notice_seen, telemetry_config_dir, monkeypatch
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\n[profile:work]\napi_host = https://artifacts.example.com\n"
    )
    monkeypatch.setenv("CLOUDSMITH_PROFILE", "work")
    _run_root(["--help"])
    assert usage_events == []


@pytest.mark.parametrize("args", [["--help"], ["no-such-command"]])
def test_config_file_cloudsmith_host_still_sends_before_config_loads(
    usage_events, notice_seen, telemetry_config_dir, args
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\napi_host = https://api.cloudsmith.io\n"
    )
    _run_root(args)
    assert len(usage_events) == 1


def test_env_api_host_beats_the_config_file_before_config_loads(
    usage_events, notice_seen, telemetry_config_dir, monkeypatch
):
    # As in initialise_session, CLOUDSMITH_API_HOST wins over config.ini.
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\napi_host = https://artifacts.example.com\n"
    )
    monkeypatch.setenv("CLOUDSMITH_API_HOST", "https://api.cloudsmith.io")
    _run_root(["--help"])
    assert len(usage_events) == 1


def test_unreadable_config_file_sends_nothing_before_config_loads(
    usage_events, notice_seen, telemetry_config_dir
):
    (telemetry_config_dir / "config.ini").write_text("[default\napi_host = x\n")
    _run_root(["--help"])
    assert usage_events == []


def _run_any(args):
    """Run ``main()`` like a user would, whatever the exit code."""
    try:
        main(args=args)
    except SystemExit:
        pass


@pytest.mark.parametrize(
    "args",
    [
        ["ls", "pkgs", "ws/r", "--config-file", "{file}", "--help"],
        ["ls", "pkgs", "--config-file", "{file}"],  # missing argument
        ["whoami", "--config-file", "{file}", "--help"],
        ["whoami", "-C", "{file}", "--help"],
        ["--config-file", "{file}", "--help"],
    ],
)
@pytest.mark.parametrize(
    "setting", ["telemetry = false", "api_host = https://artifacts.example.com"]
)
def test_typed_config_file_holds_before_the_command_loads_it(
    usage_events, notice_seen, tmp_path, args, setting
):
    path = tmp_path / "optout.ini"
    path.write_text(f"[default]\n{setting}\n")
    _run_any([arg.format(file=path) for arg in args])
    assert usage_events == []


@pytest.mark.parametrize("args", [["--profile", "p", "--help"], ["-P", "p", "-h"]])
def test_typed_profile_opt_out_holds_before_the_command_loads_it(
    usage_events, notice_seen, telemetry_config_dir, args
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\n[profile:p]\ntelemetry = false\n"
    )
    _run_any(args)
    assert usage_events == []


@pytest.mark.parametrize(
    "setting", ["telemetry = false", "api_host = https://artifacts.example.com"]
)
def test_config_file_env_holds_before_config_loads(
    usage_events, notice_seen, tmp_path, monkeypatch, setting
):
    path = tmp_path / "optout.ini"
    path.write_text(f"[default]\n{setting}\n")
    monkeypatch.setenv("CLOUDSMITH_CONFIG_FILE", str(path))
    _run_root(["--help"])
    assert usage_events == []


def test_config_file_env_without_an_opt_out_still_sends(
    usage_events, notice_seen, tmp_path, monkeypatch
):
    path = tmp_path / "plain.ini"
    path.write_text("[default]\ncheck_for_update = true\n")
    monkeypatch.setenv("CLOUDSMITH_CONFIG_FILE", str(path))
    _run_root(["--help"])
    assert len(usage_events) == 1


def test_typed_config_file_without_an_opt_out_sends_once_loaded(
    usage_events, notice_seen, no_repos_api, tmp_path
):
    # The leaf loads the file itself (and hands off through ctx.forward), so
    # the opt-out check sees what the file sets.
    path = tmp_path / "plain.ini"
    path.write_text("[default]\ncheck_for_update = true\n")
    args = ["list", "repos", "acme/x", "-F", "json", "--config-file", str(path)]
    assert main(args=args, standalone_mode=False) in (0, None)
    assert len(no_repos_api) == 1
    assert len(usage_events) == 1


def test_typed_config_file_with_an_opt_out_sends_nothing_once_loaded(
    usage_events, notice_seen, no_repos_api, tmp_path
):
    path = tmp_path / "optout.ini"
    path.write_text("[default]\ntelemetry = false\n")
    args = ["list", "repos", "acme/x", "-F", "json", "--config-file", str(path)]
    assert main(args=args, standalone_mode=False) in (0, None)
    assert usage_events == []


@pytest.mark.parametrize(
    "env, extra, setting, source, flag",
    [
        ({"CLOUDSMITH_WORKSPACE": "acme"}, [], "workspace", "env", None),
        ({}, ["-w", "acme"], "workspace", "flag", "org"),
        ({}, ["--config-file", "{file}"], "config_file_path", "flag", "config_file"),
    ],
)
def test_setting_sources_use_the_setting_names(
    usage_events,
    notice_seen,
    no_repos_api,
    tmp_path,
    monkeypatch,
    env,
    extra,
    setting,
    source,
    flag,
):
    path = tmp_path / "plain.ini"
    path.write_text("[default]\ncheck_for_update = true\n")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    args = ["list", "repos", "acme/x", "-F", "json"]
    args += [arg.format(file=path) for arg in extra]
    assert main(args=args, standalone_mode=False) in (0, None)
    props = usage_events[-1]["properties"]
    assert props[f"source_{setting}"] == source
    if flag:  # flags keep the Click parameter names
        assert flag in props["flags"]


def test_forwarding_command_keeps_the_login_method(
    usage_events, notice_seen, no_repos_api, monkeypatch
):
    # `list repos` resolves credentials again inside `repositories get`
    # (ctx.forward), where the env key is not passed on; that later None
    # must not hide the login method the run used.
    monkeypatch.setenv("CLOUDSMITH_API_KEY", "not-a-real-key")
    args = ["list", "repos", "acme/x", "-F", "json"]
    assert main(args=args, standalone_mode=False) in (0, None)
    assert usage_events[-1]["properties"]["auth_source"] == "env_var"


def test_command_that_never_logs_in_reports_no_login_method(
    usage_events, notice_seen, monkeypatch
):
    monkeypatch.setenv("CLOUDSMITH_API_KEY", "not-a-real-key")
    main(args=["credential-helper", "list"], standalone_mode=False)
    assert "auth_source" not in usage_events[-1]["properties"]
