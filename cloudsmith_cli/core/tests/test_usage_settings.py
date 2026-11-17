import pytest

from cloudsmith_cli.core.usage import settings


@pytest.fixture(autouse=True)
def isolated_config(telemetry_config_dir):
    """install_id_enabled also reads config.ini; never the developer's."""
    return telemetry_config_dir


def test_the_production_key_is_built_in():
    # Read from the source: the autouse conftest guard blanks it at runtime.
    import re

    with open(settings.__file__, encoding="utf-8") as source:
        match = re.search(
            r'^POSTHOG_PROJECT_KEY = \(?\s*"([^"]*)"', source.read(), re.M
        )
    assert match and re.fullmatch(r"phc_[A-Za-z0-9]{40,50}", match.group(1))
    assert settings.POSTHOG_HOST == "https://eu.i.posthog.com"


def test_the_override_replaces_the_key(monkeypatch):
    monkeypatch.setattr(settings, "POSTHOG_PROJECT_KEY", "phc_builtin")
    assert settings.project_key({}) == "phc_builtin"
    assert settings.override_set({}) is False
    env = {settings.KEY_ENV: "phc_test", settings.HOST_ENV: "https://eu.i.posthog.com"}
    assert settings.project_key(env) == "phc_test"
    assert settings.override_set(env) is True


def test_flags_parse_truthy_values_only():
    assert settings.internal({settings.INTERNAL_ENV: "true"}) is True
    assert settings.internal({settings.INTERNAL_ENV: "0"}) is False
    assert settings.install_id_enabled({settings.INSTALL_ID_ENV: "yes"}) is True


@pytest.mark.parametrize(
    "value", ["", "1", "true", "yes", "on", "enable", "Enabled", "anything", "log"]
)
def test_install_id_is_on_by_default(value):
    env = {settings.INSTALL_ID_ENV: value} if value else {}
    assert settings.install_id_enabled(env) is True


@pytest.mark.parametrize(
    "value", ["0", "false", "no", "off", " FALSE ", "disable", "DISABLED"]
)
def test_install_id_off_switch(value):
    assert settings.install_id_enabled({settings.INSTALL_ID_ENV: value}) is False


@pytest.mark.parametrize("value", ["disable", "off", "false", "0"])
def test_install_id_off_in_config(isolated_config, value):
    (isolated_config / "config.ini").write_text(
        f"[default]\ntelemetry_install_id = {value}\n"
    )
    assert settings.install_id_enabled({}) is False


def test_install_id_env_wins_over_config(isolated_config):
    (isolated_config / "config.ini").write_text(
        "[default]\ntelemetry_install_id = disable\n"
    )
    assert settings.install_id_enabled({settings.INSTALL_ID_ENV: "enable"}) is True
    (isolated_config / "config.ini").write_text(
        "[default]\ntelemetry_install_id = enable\n"
    )
    assert settings.install_id_enabled({settings.INSTALL_ID_ENV: "off"}) is False


@pytest.mark.parametrize("value", ["enable", "log", "nope"])
def test_install_id_config_only_turns_it_off_with_an_off_value(isolated_config, value):
    (isolated_config / "config.ini").write_text(
        f"[default]\ntelemetry_install_id = {value}\n"
    )
    assert settings.install_id_enabled({}) is True


def test_install_id_is_off_when_config_is_unreadable():
    def unreadable():
        raise OSError("unreadable")

    assert settings.install_id_enabled({}, read_config=unreadable) is False


def test_ci_sample_rate_defaults_to_100_and_clamps():
    assert settings.ci_sample_rate({}) == 100
    assert settings.ci_sample_rate({settings.SAMPLE_RATE_ENV: "10"}) == 10
    assert settings.ci_sample_rate({settings.SAMPLE_RATE_ENV: "500"}) == 100
    assert settings.ci_sample_rate({settings.SAMPLE_RATE_ENV: "x"}) == 100
