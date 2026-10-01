"""Tests for error reporting: opt-out controls, sending, and anonymisation."""

import importlib.util
import json
import socket
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from cloudsmith_cli.cli import config
from cloudsmith_cli.core import telemetry

# --- Opt-out controls -------------------------------------------------------


def test_enabled_when_nothing_set():
    assert telemetry.telemetry_disabled({}) is False


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", " yes "])
def test_truthy_value_disables(name, value):
    assert telemetry.telemetry_disabled({name: value}) is True


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
@pytest.mark.parametrize("value", ["0", "", "no", "false", "off"])
def test_other_values_leave_reporting_on(name, value):
    assert telemetry.telemetry_disabled({name: value}) is False


def test_ci_does_not_disable():
    assert telemetry.telemetry_disabled({"CI": "true"}) is False


def test_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv(telemetry.DO_NOT_TRACK_ENV, "1")
    assert telemetry.telemetry_disabled() is True


def test_dsn_override():
    assert telemetry.get_dsn({telemetry.DSN_ENV: " https://k@h/1 "}) == "https://k@h/1"
    assert telemetry.get_dsn({telemetry.DSN_ENV: ""}) == ""
    assert telemetry.get_dsn({}) == telemetry.DSN


@pytest.mark.parametrize(
    "path,frozen,expected",
    [
        (
            "/x/.venv/lib/python3.12/site-packages/cloudsmith_cli/core/t.py",
            False,
            "production",
        ),
        (
            "/usr/lib/python3/dist-packages/cloudsmith_cli/core/t.py",
            False,
            "production",
        ),
        ("C:\\Py\\Lib\\site-packages\\cloudsmith_cli\\core\\t.py", False, "production"),
        ("/home/dev/src/cloudsmith-cli/cloudsmith_cli/core/t.py", False, "development"),
        ("/opt/bundle/_internal/cloudsmith_cli/core/t.py", True, "production"),
    ],
)
def test_environment(path, frozen, expected):
    assert telemetry.get_environment(path, frozen=frozen) == expected


# --- Sending ----------------------------------------------------------------


def raise_and_catch(exc):
    try:
        raise exc
    except BaseException as caught:  # pylint: disable=broad-exception-caught
        return caught


def test_reports_one_event(sentry_events):
    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is True

    assert len(sentry_events) == 1
    (exc,) = sentry_events[0]["exception"]["values"]
    assert exc["type"] == "RuntimeError"
    assert exc["value"] == "boom"
    assert exc["mechanism"]["handled"] is False
    assert sentry_events[0]["release"].startswith("cloudsmith-cli@")


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
def test_opted_out_sends_nothing(sentry_events, monkeypatch, name):
    monkeypatch.setenv(name, "1")

    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False
    assert sentry_events == []


def test_empty_dsn_sends_nothing(sentry_events, monkeypatch):
    monkeypatch.setenv(telemetry.DSN_ENV, "")

    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False
    assert sentry_events == []


def test_report_is_silent(sentry_events, capsys):
    telemetry.report_exception(raise_and_catch(RuntimeError("boom")))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("error", [OSError("broken"), KeyboardInterrupt()])
def test_transport_failure_never_raises(sentry_events, monkeypatch, error):
    # pylint: disable=protected-access
    def explode(envelope):
        raise error

    monkeypatch.setattr(telemetry._transport, "capture_envelope", explode)

    telemetry.report_exception(raise_and_catch(RuntimeError("boom")))


def test_invalid_dsn_never_raises(sentry_events, monkeypatch):
    # The real transport parses the DSN; an injected one skips that.
    monkeypatch.setattr(telemetry, "_transport", None)
    monkeypatch.setenv(telemetry.DSN_ENV, "not a dsn")

    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False


@pytest.fixture()
def unresponsive_server():
    """A TCP server that accepts connections and never replies."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    stop = threading.Event()
    held = []

    def accept():
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for conn in held:
        conn.close()
    server.close()


def test_hung_sentry_is_bounded_by_the_flush_timeout(
    sentry_events, monkeypatch, unresponsive_server, capfd
):
    """A Sentry outage costs at most the flush timeout and prints nothing.

    Uses the real HTTP transport against a server that never replies.
    """
    monkeypatch.setattr(telemetry, "_transport", None)
    monkeypatch.setattr(telemetry, "FLUSH_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setenv(
        telemetry.DSN_ENV, f"http://publickey@127.0.0.1:{unresponsive_server}/1"
    )

    start = time.monotonic()
    telemetry.report_exception(raise_and_catch(RuntimeError("boom")))

    assert time.monotonic() - start < 2.0
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_sentry_sdk_not_imported_when_opted_out():
    code = textwrap.dedent(
        """
        import os, sys
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["CLOUDSMITH_TELEMETRY_DSN"] = "https://k@o0.ingest.sentry.invalid/0"
        from cloudsmith_cli.core import telemetry
        telemetry.report_exception(RuntimeError("boom"))
        print("sentry_sdk" in sys.modules)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


# --- Anonymisation of a real traceback --------------------------------------

USERNAME = "alice-smith"
HOSTNAME = "alice-mbp.corp.example"
ENV_API_KEY = "csk-env-0123456789abcdef"
FILE_API_KEY = "csk-file-fedcba9876543210"
SLUG = "acme-workspace-slug"
PASSWORD = "hunter2-very-secret"

FAKE_MODULE = """
def push_package(path, api_key):
    workspace = {slug!r}
    password = {password!r}
    raise FileNotFoundError(
        f"cannot read {{path}} with {{api_key}} via "
        "https://bob:pw@cloudsmith.acme.internal/api/ for {username}@{hostname}"
    )
"""


@pytest.fixture()
def anonymity_env(tmp_path, monkeypatch):
    """A fake user, machine and credentials, with code living in their home."""
    home = tmp_path / "home" / USERNAME
    project = home / "projects" / "tool"
    project.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for name in ("USER", "USERNAME", "LOGNAME"):
        monkeypatch.setenv(name, USERNAME)
    monkeypatch.setattr(telemetry, "_username", lambda: USERNAME)
    monkeypatch.setattr(telemetry, "_hostname", lambda: HOSTNAME)
    monkeypatch.setenv("CLOUDSMITH_API_KEY", ENV_API_KEY)
    # A credential resolved from credentials.ini / the keyring, not the env.
    monkeypatch.setattr(
        config.OPTIONS,
        "value",
        SimpleNamespace(api_key=FILE_API_KEY, credential=None, api_config=None),
        raising=False,
    )

    module_path = project / "acme_tool.py"
    module_path.write_text(
        FAKE_MODULE.format(
            slug=SLUG, password=PASSWORD, username=USERNAME, hostname=HOSTNAME
        )
    )
    spec = importlib.util.spec_from_file_location("acme_tool", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(home=home, module=module)


@pytest.fixture()
def scrubbed_event(anonymity_env, sentry_events):
    try:
        anonymity_env.module.push_package(
            str(anonymity_env.home / "pkgs" / "acme-pkg-1.0.whl"), FILE_API_KEY
        )
    except FileNotFoundError as exc:
        assert telemetry.report_exception(exc) is True

    (event,) = sentry_events
    return event


@pytest.mark.parametrize(
    "secret",
    [
        USERNAME,
        HOSTNAME,
        HOSTNAME.split(".", maxsplit=1)[0],
        ENV_API_KEY,
        FILE_API_KEY,
        SLUG,
        PASSWORD,
        "bob:pw",
        "acme.internal",
    ],
)
def test_no_identifier_or_secret_anywhere(scrubbed_event, secret):
    assert secret.lower() not in json.dumps(scrubbed_event).lower()


def test_no_real_paths_or_machine_identity(scrubbed_event, anonymity_env, tmp_path):
    serialised = json.dumps(scrubbed_event)

    assert str(tmp_path) not in serialised
    assert str(anonymity_env.home) not in serialised


def test_home_paths_are_abbreviated(scrubbed_event):
    (exc,) = scrubbed_event["exception"]["values"]
    frame = exc["stacktrace"]["frames"][-1]

    assert frame["function"] == "push_package"
    assert frame["abs_path"] == "~/projects/tool/acme_tool.py"
    assert "~/pkgs/acme-pkg-1.0.whl" in exc["value"]


def test_message_keeps_its_shape(scrubbed_event):
    (exc,) = scrubbed_event["exception"]["values"]

    assert exc["value"] == (
        "cannot read ~/pkgs/acme-pkg-1.0.whl with [redacted] via "
        "https://[redacted]@<host>/api/ for <user>@<host>"
    )


def test_frames_carry_no_locals_or_source(scrubbed_event):
    (exc,) = scrubbed_event["exception"]["values"]

    for frame in exc["stacktrace"]["frames"]:
        assert set(frame) <= {
            "filename",
            "abs_path",
            "module",
            "function",
            "lineno",
            "in_app",
        }


def test_only_allowlisted_fields(scrubbed_event):
    assert set(scrubbed_event) <= set(telemetry._TOP_LEVEL_KEYS) | {  # pylint: disable=protected-access
        "exception",
        "tags",
        "contexts",
    }
    for absent in ("user", "request", "breadcrumbs", "server_name", "extra", "modules"):
        assert absent not in scrubbed_event
    assert set(scrubbed_event["tags"]) <= {"command", "channel", "arch", "frozen"}
    assert set(scrubbed_event["contexts"]) <= {"os", "runtime"}
    for context in scrubbed_event["contexts"].values():
        assert set(context) <= {"name", "version"}


def test_environment_metadata_is_present(scrubbed_event):
    assert scrubbed_event["tags"]["command"] == "<unknown>"
    assert scrubbed_event["tags"]["channel"]
    assert scrubbed_event["contexts"]["runtime"]["version"]
    assert scrubbed_event["contexts"]["os"]["name"]


def test_scrub_event_fails_closed():
    assert telemetry.scrub_event({"exception": "not-a-dict"}) is None


# --- Scrubber unit tests ----------------------------------------------------


def scrubber(**kwargs):
    return telemetry.Scrubber(**kwargs)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/home/alice/x.whl", "~/x.whl"),
        ("/home/alice", "~"),
        ("open '/home/alice/a b.txt'", "open '~/a b.txt'"),
        # Path boundary: a sibling directory that shares the prefix is untouched.
        ("/home/alicex/y", "/home/alicex/y"),
    ],
)
def test_posix_home(text, expected):
    assert scrubber(home=["/home/alice"]).scrub(text) == expected


def test_windows_home_any_case_and_separator():
    s = scrubber(home=["C:\\Users\\Alice"], case_insensitive=True)

    assert s.scrub("c:\\users\\alice\\pkg.whl") == "~\\pkg.whl"
    assert s.scrub("C:/Users/Alice/pkg.whl") == "~/pkg.whl"


def test_most_specific_prefix_wins():
    s = scrubber(
        home=["/home/alice"],
        path_prefixes=[("/home/alice/proj/.venv", "<prefix>")],
    )

    assert s.scrub("/home/alice/proj/.venv/lib/x.py") == "<prefix>/lib/x.py"
    assert s.scrub("/home/alice/proj/y.py") == "~/proj/y.py"


def test_shallow_prefixes_are_ignored():
    s = scrubber(path_prefixes=[("/usr", "<prefix>"), ("/", "<root>")])

    assert s.scrub("/usr/lib/x.py") == "/usr/lib/x.py"


def test_root_home_is_still_scrubbed():
    assert scrubber(home=["/root"]).scrub("/root/.config/x") == "~/.config/x"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("owned by alice.", "owned by <user>."),
        ("ALICE@host", "<user>@host"),
        ("malice and alice-2", "malice and alice-2"),
    ],
)
def test_username_as_word(text, expected):
    assert scrubber(usernames=["alice"]).scrub(text) == expected


def test_short_identifiers_are_not_scrubbed():
    assert scrubber(usernames=["ci"]).scrub("ci failed") == "ci failed"


def test_hostname():
    s = scrubber(hostnames=["build-07.corp", "build-07"])

    assert s.scrub("on build-07.corp and build-07") == "on <host> and <host>"


def test_secrets():
    s = scrubber(secrets=["s3cr3t-value-123", "short"])

    assert s.scrub("key=s3cr3t-value-123") == "key=[redacted]"
    assert s.scrub("a short word") == "a short word"


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "https://bob:pw@api.cloudsmith.io/x",
            "https://[redacted]@api.cloudsmith.io/x",
        ),
        ("https://api.cloudsmith.io/v1/", "https://api.cloudsmith.io/v1/"),
        ("https://dl.cloudsmith.com/x", "https://dl.cloudsmith.com/x"),
        ("https://cs.acme.internal/v1", "https://<host>/v1"),
        ("https://evilcloudsmith.io/v1", "https://<host>/v1"),
        (
            "HTTPSConnectionPool(host='10.0.0.5', port=443)",
            "HTTPSConnectionPool(host='<host>', port=443)",
        ),
    ],
)
def test_hosts_and_url_credentials(text, expected):
    assert scrubber().scrub(text) == expected
