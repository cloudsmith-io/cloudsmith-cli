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
def sentry_events(monkeypatch):
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
