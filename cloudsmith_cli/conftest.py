import json

import cloudsmith_api
import pytest

from cloudsmith_cli.core import keyring as core_keyring
from cloudsmith_cli.core import session, telemetry

#: A syntactically valid DSN that is never contacted: tests that report use
#: an in-memory transport.
FAKE_DSN = "https://publickey@o0.ingest.sentry.invalid/0"


@pytest.fixture(autouse=True)
def no_real_error_reports(monkeypatch):
    """Never send a real error report from the test suite.

    Tests that exercise reporting opt back in with ``sentry_events``.
    """
    monkeypatch.setenv(telemetry.NO_TELEMETRY_ENV, "1")
    monkeypatch.setenv(telemetry.DSN_ENV, "")
    monkeypatch.setattr(telemetry, "_transport", None)


@pytest.fixture(autouse=True)
def default_keyring_settings():
    """Start each test with the default keyring settings."""
    core_keyring.configure(core_keyring.KeyringSettings())


@pytest.fixture()
def telemetry_config_dir(monkeypatch, tmp_path_factory):
    """An empty config search path, isolated from the developer's config.ini.

    Reporting reads ``telemetry`` from config.ini, so without this a local
    ``telemetry = false`` (or a broken file) would change test outcomes.
    Write a ``config.ini`` into the returned directory to set the key.
    """
    from cloudsmith_cli.cli import config

    path = tmp_path_factory.mktemp("telemetry-config")
    # Basenames only: --config-file paths from earlier tests are inserted into
    # these class-level lists and would otherwise still be read.
    for reader, name in (
        (config.ConfigReader, "config.ini"),
        (config.CredentialsReader, "credentials.ini"),
    ):
        monkeypatch.setattr(reader, "config_files", [name])
        monkeypatch.setattr(reader, "config_searchpath", [str(path)])
    monkeypatch.delenv(telemetry.PROFILE_ENV, raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    return path


@pytest.fixture()
def sentry_events(monkeypatch, telemetry_config_dir):  # pylint: disable=unused-argument
    """Enable reporting into an in-memory transport; yield the sent events."""
    from sentry_sdk.transport import Transport

    events = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            events.extend(
                item.payload.json for item in envelope.items if item.type == "event"
            )

    for name in telemetry.OPT_OUT_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(telemetry.DSN_ENV, FAKE_DSN)
    monkeypatch.setattr(telemetry, "_transport", CaptureTransport())
    return events


@pytest.fixture(autouse=True)
def restore_api_configuration_default():
    """Undo the process-wide SDK configuration a test leaves behind.

    ``initialise_api`` ends in ``Configuration.set_default()``, so a test that
    sets a proxy, host or credential would otherwise hand it to every test that
    runs after it. A fresh ``Configuration`` is a copy of the current default,
    which makes it the snapshot to put back afterwards.
    """
    default = cloudsmith_api.Configuration()
    yield
    cloudsmith_api.Configuration.set_default(default)


@pytest.fixture(autouse=True)
def restore_default_proxy():
    """Clear the process-wide proxy that ``initialise_session`` sets."""
    yield
    session.set_default_proxy(None)


@pytest.fixture(autouse=True)
def reset_wait_budget():
    """Give every test a full shared exit-wait budget."""
    from cloudsmith_cli.core import telemetry_common

    telemetry_common.WaitBudget.shared().reset(1.0)


@pytest.fixture(autouse=True)
def usage_state_dir(monkeypatch, tmp_path_factory):
    """Keep usage telemetry state out of the developer's real config dir."""
    path = tmp_path_factory.mktemp("usage-state")
    monkeypatch.setattr("cloudsmith_cli.core.usage.state.config_dir", lambda: str(path))
    return path


@pytest.fixture(autouse=True)
def blocked_usage_posts(monkeypatch):
    """Never send a real usage event from the test suite.

    Removes the developer's usage settings (AGENTS.md tells them to export a
    test key) and replaces the POST with one that records the call and fails.
    The sender swallows that failure in its thread, so the fixture fails the
    test at teardown if any call was recorded. A test that expects a refused
    call asserts on the returned list and clears it. Tests that exercise
    sending opt back in with ``usage_events``.
    """
    from cloudsmith_cli.core.usage import sender, settings

    calls = []

    def refuse(*args, **kwargs):  # pylint: disable=unused-argument
        calls.append(args)
        raise AssertionError("unit tests must not send usage telemetry")

    for name in (
        settings.KEY_ENV,
        settings.HOST_ENV,
        settings.MODE_ENV,
        settings.INSTALL_ID_ENV,
        settings.INTERNAL_ENV,
        settings.SAMPLE_RATE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sender, "_post", refuse)
    yield calls
    if calls:
        pytest.fail(f"unit test attempted {len(calls)} usage telemetry send(s)")


@pytest.fixture()
def usage_events(monkeypatch, telemetry_config_dir, blocked_usage_posts):  # pylint: disable=unused-argument
    """Enable usage telemetry into a list instead of the network."""
    from cloudsmith_cli.core import telemetry_common
    from cloudsmith_cli.core.usage import environment, sender

    events = []
    for name in telemetry.OPT_OUT_ENVS:
        monkeypatch.delenv(name, raising=False)
    ci_names = [name for _, names in environment._CI_PROVIDERS for name in names] + [
        "KUBERNETES_SERVICE_HOST"
    ]
    # Tests may themselves run under an AI agent, which sets these.
    agent_names = [
        name for _, names in environment._AGENT_MARKERS for name in names
    ] + [environment.AI_AGENT_ENV]
    for name in (
        ci_names
        + agent_names
        + [
            "CLOUDSMITH_TELEMETRY",
            "CLOUDSMITH_TELEMETRY_CI_SAMPLE_RATE",
            "CLOUDSMITH_TELEMETRY_INSTALL_ID",
            "CLOUDSMITH_TELEMETRY_POSTHOG_HOST",
            "CLOUDSMITH_TELEMETRY_INTERNAL",
            "CLOUDSMITH_API_HOST",
            "CLOUDSMITH_SSL_VERIFY",
            "CLOUDSMITH_WITHOUT_API_SSL_VERIFY",
        ]
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    # Later tests that call the real main() must never run the update check's
    # network fetch.
    monkeypatch.setenv("CLOUDSMITH_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(environment, "is_container", lambda: False)
    monkeypatch.setattr(
        sender,
        "_post",
        lambda session, url, body, timeout: events.append(json.loads(body)) or True,
    )
    telemetry_common.WaitBudget.shared().reset(1.0)
    return events
