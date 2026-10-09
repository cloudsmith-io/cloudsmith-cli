import cloudsmith_api
import pytest

from cloudsmith_cli.core import telemetry

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
