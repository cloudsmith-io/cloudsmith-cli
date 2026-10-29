import pytest

from cloudsmith_cli.core.usage import event
from cloudsmith_cli.core.usage.identity import Identity


def _facts(**overrides):
    base = dict(
        command="list repos",
        flags=["output_format", "page_size"],
        flags_typed=["-F", "--page-size"],
        envvars=["NO_COLOR"],
        aliases_used=["ls"],
        output_format="json",
        outcome="success",
        exit_code=0,
        api_status=None,
        duration_ms=708,
        setting_sources={"workspace": "config_file", "color": "env"},
        auth_source="keyring",
        api_host=None,
        ssl_verify=True,
        stdout_tty=False,
        stdin_tty=False,
        nested=False,
    )
    base.update(overrides)
    return event.RunFacts(**base)


def _build(facts, anonymous=True):
    ident = Identity(
        "id-1", anonymous=anonymous, first_run=False, persisted=not anonymous
    )
    return event.build_event(
        facts=facts,
        identity=ident,
        runtime={
            "os": "Darwin",
            "os_version": "26.3",
            "python_version": "3.12",
            "arch": "arm64",
        },
        channel="pip",
        environment="production",
        cli_version="1.31.0",
        ci_provider=None,
        sample_rate=100,
        internal=False,
        timestamp="2026-10-23T12:00:00+00:00",
    )


def test_only_declared_properties_are_sent():
    declared = {p.name for p in event.PROPERTIES}
    props = _build(_facts())["properties"]
    for key in props:
        assert key in declared or (
            key.startswith("source_")
            and key[len("source_") :] in event.ALLOWED_SETTINGS
        ), key


def test_snapshot_of_a_typical_event():
    payload = _build(_facts())
    assert payload["event"] == "cli command executed"
    assert payload["distinct_id"] == "id-1"
    props = payload["properties"]
    assert props["$process_person_profile"] is False
    assert props["$geoip_disable"] is True
    assert props["command"] == "list repos"
    assert props["flags_typed"] == ["--page-size", "-F"]
    assert props["source_workspace"] == "config_file"
    assert props["persona"] == "human"
    assert "api_status" not in props  # None values are dropped


def test_install_id_event_creates_no_person_profile():
    # A stable install ID still never creates a person profile.
    props = _build(_facts(), anonymous=False)["properties"]
    assert props["$process_person_profile"] is False


def test_unknown_setting_or_source_is_dropped():
    props = _build(
        _facts(setting_sources={"secret_thing": "env", "workspace": "weird"})
    )["properties"]
    assert not any(k.startswith("source_") for k in props)


def test_wrong_type_is_dropped():
    props = _build(_facts(duration_ms="708"))["properties"]
    assert "duration_ms" not in props


@pytest.mark.parametrize("name", ["flags", "flags_typed", "envvars", "aliases_used"])
@pytest.mark.parametrize("bad", ["--page-size", None, ["ok", 3], {"a": 1}, 7])
def test_malformed_name_lists_are_dropped_not_split(name, bad):
    # A bare string must not be sent one character at a time, and None or
    # non-string items must not raise.
    props = _build(_facts(**{name: bad}))["properties"]
    assert name not in props


def test_name_lists_are_deduplicated_and_sorted_but_aliases_keep_order():
    props = _build(
        _facts(
            flags=("page_size", "output_format", "page_size"),
            aliases_used=["ls", "repos"],
        )
    )["properties"]
    assert props["flags"] == ["output_format", "page_size"]
    assert props["aliases_used"] == ["ls", "repos"]
