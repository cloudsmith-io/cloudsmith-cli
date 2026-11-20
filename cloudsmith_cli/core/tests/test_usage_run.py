# pylint: disable=unused-argument
import pytest

from cloudsmith_cli.core.usage import notice, run, state
from cloudsmith_cli.core.usage.event import RunFacts


def facts(**kw):
    return RunFacts(command=kw.pop("command", "whoami"), **kw)


@pytest.fixture()
def interactive():
    """A human at a terminal whose notice was already shown."""
    state.write({"notice_version": notice.NOTICE_VERSION})


def test_sends_one_event(usage_events, interactive):
    run.finish(facts())
    assert len(usage_events) == 1
    assert usage_events[0]["properties"]["command"] == "whoami"


@pytest.mark.parametrize(
    "command",
    [
        "credential-helper docker",
        "credential-helper terraform",
        "mcp start",
        "telemetry reset",
    ],
)
def test_excluded_commands_send_nothing_and_touch_no_state(usage_events, command):
    run.finish(facts(command=command))
    assert usage_events == [] and state.read() == {}


def test_opt_out_sends_nothing(usage_events, interactive, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    run.finish(facts())
    assert usage_events == []


def test_custom_api_host_sends_nothing(usage_events, interactive):
    run.finish(facts(api_host="https://artifacts.example.com"))
    assert usage_events == []


def test_ssl_verify_disabled_sends_nothing(usage_events, interactive):
    run.finish(facts(ssl_verify=False))
    assert usage_events == []


def test_dev_build_without_override_sends_nothing(
    usage_events, interactive, monkeypatch
):
    monkeypatch.delenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY")
    run.finish(facts())
    assert usage_events == []


def test_first_interactive_run_shows_notice_and_sends_nothing(usage_events, capsys):
    run.finish(facts(stdout_tty=True, stdin_tty=True))
    assert usage_events == []
    assert "usage data" in capsys.readouterr().err
    run.finish(facts(stdout_tty=True, stdin_tty=True))
    assert len(usage_events) == 1


def test_ci_sends_from_first_run_without_notice(usage_events, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    # TTYs, so only CI (not a missing terminal) keeps the notice away.
    run.finish(facts(stdout_tty=True, stdin_tty=True))
    assert len(usage_events) == 1
    props = usage_events[0]["properties"]
    assert props["ci_provider"] == "github_actions"
    assert props["$process_person_profile"] is False
    assert capsys.readouterr().err == ""
    assert state.read() == {}


def test_ci_sampling_zero_sends_nothing(usage_events, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_CI_SAMPLE_RATE", "0")
    run.finish(facts())
    assert usage_events == []


def test_ci_sample_rate_never_samples_runs_outside_ci(usage_events, monkeypatch):
    # Unwritable state makes the run ephemeral, but it is not CI.
    monkeypatch.setattr(state, "writable", lambda: False)
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_CI_SAMPLE_RATE", "0")
    run.finish(facts())
    assert len(usage_events) == 1
    props = usage_events[0]["properties"]
    assert props["sample_rate"] == 100 and props["ci"] is False


def test_container_runs_are_not_ci_sampled(usage_events, monkeypatch):
    from cloudsmith_cli.core.usage import environment

    monkeypatch.setattr(environment, "is_container", lambda: True)
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_CI_SAMPLE_RATE", "0")
    run.finish(facts())
    assert len(usage_events) == 1


def test_resolved_ssl_strictness_reaches_the_sender(
    usage_events, interactive, monkeypatch
):
    from cloudsmith_cli.core.usage import sender

    seen = []
    monkeypatch.setattr(
        sender, "send", lambda payload, strict=None: seen.append(strict) or True
    )
    run.finish(facts(ssl_verify_strict=False))
    assert seen == [False]


def test_failed_send_backs_off_for_a_day(usage_events, interactive, monkeypatch):
    from cloudsmith_cli.core.usage import sender

    monkeypatch.setattr(sender, "send", lambda payload, *_: False)
    run.finish(facts())
    assert state.read().get("last_failure_at")
    monkeypatch.setattr(
        sender, "send", lambda payload, *_: usage_events.append(payload) or True
    )
    run.finish(facts())
    assert usage_events == []


def test_skipped_send_does_not_back_off(usage_events, interactive, monkeypatch):
    from cloudsmith_cli.core.usage import sender

    monkeypatch.setattr(sender, "send", lambda payload, *_: None)
    run.finish(facts())
    assert "last_failure_at" not in state.read()


def test_log_mode_prints_and_sends_nothing(
    usage_events, interactive, monkeypatch, capsys
):
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY", "log")
    run.finish(facts())
    assert usage_events == []
    assert "would send" in capsys.readouterr().err


def test_nested_run_sends_nothing(usage_events, interactive):
    run.finish(facts(nested=True))
    assert usage_events == []


def test_finish_never_raises(usage_events, interactive, monkeypatch):
    from cloudsmith_cli.core.usage import event

    monkeypatch.setattr(event, "build_event", lambda **kw: 1 / 0)
    run.finish(facts())  # must not raise


def test_unwritable_state_is_ephemeral(usage_events, monkeypatch, capsys):
    monkeypatch.setattr(state, "writable", lambda: False)
    run.finish(facts(stdout_tty=True, stdin_tty=True))
    assert len(usage_events) == 1
    assert usage_events[0]["properties"]["$process_person_profile"] is False
    assert capsys.readouterr().err == ""
    assert state.read() == {}


def test_dev_build_gate_alone_blocks_log_mode(usage_events, monkeypatch, capsys):
    monkeypatch.delenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY")
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY", "log")
    run.finish(facts())
    assert usage_events == []
    assert "would send" not in capsys.readouterr().err


def test_failed_ephemeral_send_does_no_state_io(usage_events, monkeypatch):
    from cloudsmith_cli.core.usage import sender

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sender, "send", lambda payload, *_: False)
    run.finish(facts())
    assert state.read() == {}


def test_no_telemetry_env_sends_nothing(usage_events, interactive, monkeypatch):
    monkeypatch.setenv("CLOUDSMITH_NO_TELEMETRY", "1")
    run.finish(facts())
    assert usage_events == []


def test_config_file_opt_out_sends_nothing(
    usage_events, interactive, telemetry_config_dir
):
    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = false\n")
    run.finish(facts())
    assert usage_events == []


def test_credential_helper_install_still_sends(usage_events, interactive):
    run.finish(facts(command="credential-helper install"))
    assert len(usage_events) == 1


class _Loader:
    """A deferred-sources loader that records how often it ran."""

    def __init__(self, result=None, error=None):
        self.calls = 0
        self.result = result or {}
        self.error = error

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_excluded_command_never_loads_deferred_sources(usage_events):
    loader = _Loader({"workspace": "config_file"})
    run.finish(facts(command="credential-helper docker", deferred_sources=loader))
    assert loader.calls == 0 and usage_events == []


def test_unresolved_config_sends_nothing_and_reads_nothing(usage_events, interactive):
    # A typed --config-file or --profile that no command loaded.
    loader = _Loader({"workspace": "config_file"})
    run.finish(facts(config_unresolved=True, deferred_sources=loader))
    assert loader.calls == 0 and usage_events == []


def test_opted_out_run_never_loads_deferred_sources(
    usage_events, interactive, monkeypatch
):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    loader = _Loader({"workspace": "config_file"})
    run.finish(facts(deferred_sources=loader))
    assert loader.calls == 0 and usage_events == []


def test_deferred_sources_load_once_and_reach_the_event(usage_events, interactive):
    loader = _Loader({"workspace": "config_file"})
    run.finish(facts(deferred_sources=loader))
    assert loader.calls == 1
    assert usage_events[0]["properties"]["source_workspace"] == "config_file"


def test_click_source_wins_over_the_loaded_one(usage_events, interactive):
    loader = _Loader({"workspace": "config_file", "api_host": "config_file"})
    run.finish(facts(setting_sources={"workspace": "flag"}, deferred_sources=loader))
    props = usage_events[0]["properties"]
    assert props["source_workspace"] == "flag"
    assert props["source_api_host"] == "config_file"


def test_failing_loader_still_sends_the_event(usage_events, interactive):
    run.finish(
        facts(
            setting_sources={"workspace": "env"},
            deferred_sources=_Loader(error=RuntimeError("boom")),
        )
    )
    assert len(usage_events) == 1
    assert usage_events[0]["properties"]["source_workspace"] == "env"


@pytest.fixture()
def config_reads(monkeypatch):
    """Count config.ini reads; no command loaded config (no options yet)."""
    from cloudsmith_cli.cli import config

    monkeypatch.delattr(config.OPTIONS, "value", raising=False)
    calls = []
    real = config.ConfigReader.load_config.__func__

    def counting(cls, opts, path=None, profile=None):
        calls.append(profile)
        return real(cls, opts, path=path, profile=profile)

    monkeypatch.setattr(config.ConfigReader, "load_config", classmethod(counting))
    return calls


def test_config_file_is_read_once_per_finish(
    usage_events, interactive, telemetry_config_dir, config_reads
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\napi_host = https://api.cloudsmith.io\nssl_verify = true\n"
    )
    run.finish(facts())
    assert len(usage_events) == 1
    assert len(config_reads) == 1


@pytest.mark.parametrize(
    "setting", ["api_host = https://artifacts.example.com", "ssl_verify = false"]
)
def test_config_file_gate_blocks_with_one_read(
    usage_events, interactive, telemetry_config_dir, config_reads, setting
):
    (telemetry_config_dir / "config.ini").write_text(f"[default]\n{setting}\n")
    run.finish(facts())
    assert usage_events == []
    assert len(config_reads) == 1


def test_resolved_host_wins_over_the_config_file(
    usage_events, interactive, telemetry_config_dir, config_reads
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\napi_host = https://artifacts.example.com\n"
    )
    run.finish(facts(api_host="https://api.cloudsmith.io"))
    assert len(usage_events) == 1


def test_loaded_config_skips_the_config_file_gate(
    usage_events, interactive, telemetry_config_dir, config_reads, monkeypatch
):
    # A command that loaded config already put config.ini's host and SSL
    # setting into the facts, through opts.
    from cloudsmith_cli.cli import config

    monkeypatch.setattr(config.OPTIONS, "value", config.Options(), raising=False)
    (telemetry_config_dir / "config.ini").write_text("[default]\nssl_verify = false\n")
    run.finish(facts())
    assert len(usage_events) == 1


def test_opted_out_run_reads_no_config(
    usage_events, interactive, telemetry_config_dir, config_reads, monkeypatch
):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\napi_host = https://artifacts.example.com\n"
    )
    run.finish(facts())
    assert usage_events == [] and config_reads == []


def test_config_opt_out_reads_config_only_once(
    usage_events, interactive, telemetry_config_dir, config_reads
):
    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = false\n")
    run.finish(facts())
    assert usage_events == [] and len(config_reads) == 1


def test_config_file_gate_fails_closed(config_reads):
    def unreadable():
        raise OSError("unreadable")

    assert run._config_file_blocks(facts(), unreadable) is True  # pylint: disable=protected-access


def test_laptop_run_keeps_an_install_id_by_default(usage_events, interactive):
    # No CLOUDSMITH_TELEMETRY_INSTALL_ID needed (the fixture clears it).
    run.finish(facts())
    run.finish(facts())
    first, second = usage_events
    assert first["distinct_id"] == second["distinct_id"]
    assert first["properties"]["install_id_persisted"] is True
    assert first["properties"]["first_run"] is True
    assert second["properties"]["first_run"] is False
    assert second["properties"]["$process_person_profile"] is False
    assert state.read()["install_id"] == first["distinct_id"]


@pytest.fixture()
def stored_id(usage_events, interactive):
    run.finish(facts())
    (sent,) = usage_events
    assert state.read()["install_id"] == sent["distinct_id"]
    usage_events.clear()
    return sent["distinct_id"]


@pytest.mark.parametrize("name", ["DO_NOT_TRACK", "CLOUDSMITH_NO_TELEMETRY"])
def test_env_opt_out_deletes_the_install_id(stored_id, usage_events, monkeypatch, name):
    monkeypatch.setenv(name, "1")
    run.finish(facts())
    assert usage_events == []
    assert "install_id" not in state.read() and "created_at" not in state.read()
    # The notice was already shown; opting out does not forget that.
    assert state.read()["notice_version"] == notice.NOTICE_VERSION


def test_config_opt_out_deletes_the_install_id(
    stored_id, usage_events, telemetry_config_dir
):
    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = false\n")
    run.finish(facts())
    assert usage_events == [] and "install_id" not in state.read()


def test_unreadable_config_keeps_the_install_id(
    stored_id, usage_events, telemetry_config_dir
):
    # Fails closed (nothing sent), but a broken file is not an opt-out.
    (telemetry_config_dir / "config.ini").write_text("[default\ntelemetry = x\n")
    run.finish(facts())
    assert usage_events == [] and state.read()["install_id"] == stored_id


def test_opted_out_run_creates_no_state_file(
    usage_events, usage_state_dir, monkeypatch
):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    run.finish(facts())
    assert not usage_state_dir.joinpath(state.STATE_FILE_NAME).exists()


def test_opting_back_in_creates_a_new_install_id(stored_id, usage_events, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    run.finish(facts())
    monkeypatch.delenv("DO_NOT_TRACK")
    run.finish(facts())
    (sent,) = usage_events
    assert sent["distinct_id"] != stored_id
    assert sent["properties"]["first_run"] is True


def test_excluded_command_keeps_the_install_id_when_opted_out(stored_id, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    run.finish(facts(command="credential-helper docker"))
    assert state.read()["install_id"] == stored_id


def test_install_id_off_switch_gives_one_off_ids(
    usage_events, interactive, monkeypatch
):
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_INSTALL_ID", "0")
    run.finish(facts())
    run.finish(facts())
    first, second = usage_events
    assert first["distinct_id"] != second["distinct_id"]
    assert "install_id" not in state.read()
