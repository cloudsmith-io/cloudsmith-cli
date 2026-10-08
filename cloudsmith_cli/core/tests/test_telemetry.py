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


def test_default_dsn_is_a_public_ingest_key():
    """Guard against committing a secret-bearing (legacy) DSN or a non-Sentry host."""
    from urllib.parse import urlsplit

    parts = urlsplit(telemetry.DSN)

    assert parts.scheme == "https"
    assert parts.username
    assert parts.password is None  # legacy "key:secret@" DSNs carry a secret
    assert parts.hostname.endswith(".sentry.io")
    assert ".ingest." in f".{parts.hostname}"
    assert parts.path.strip("/").isdigit()


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


def test_user_errors_are_not_reported(sentry_events):
    from cloudsmith_cli.core.api.exceptions import TwoFactorRequiredException

    exc = raise_and_catch(TwoFactorRequiredException("2fa-token"))

    assert telemetry.is_reportable(exc) is False
    assert telemetry.report_exception(exc) is False
    assert sentry_events == []


def test_user_error_marker_is_inherited(sentry_events):
    class UserError(Exception):
        report_to_telemetry = False

    class SpecificUserError(UserError):
        pass

    assert telemetry.report_exception(raise_and_catch(SpecificUserError())) is False
    assert sentry_events == []


def test_exceptions_are_reportable_by_default():
    assert telemetry.is_reportable(RuntimeError("boom")) is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_config_key_off_sends_nothing(sentry_events, telemetry_config_dir, value):
    (telemetry_config_dir / "config.ini").write_text(
        f"[default]\ntelemetry = {value}\n"
    )

    assert telemetry.config_disabled() is True
    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False
    assert sentry_events == []


@pytest.mark.parametrize(
    "content",
    ["", "[default]\n", "[default]\ntelemetry =\n", "[default]\ntelemetry = true\n"],
)
def test_config_key_default_or_true_reports(
    sentry_events, telemetry_config_dir, content
):
    (telemetry_config_dir / "config.ini").write_text(content)

    assert telemetry.config_disabled() is False
    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is True


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
def test_config_true_does_not_override_env_opt_out(
    sentry_events, telemetry_config_dir, monkeypatch, name
):
    (telemetry_config_dir / "config.ini").write_text("[default]\ntelemetry = true\n")
    monkeypatch.setenv(name, "1")

    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False
    assert sentry_events == []


def test_config_key_in_env_selected_profile(
    sentry_events, telemetry_config_dir, monkeypatch
):
    (telemetry_config_dir / "config.ini").write_text(
        "[default]\n[profile:work]\ntelemetry = false\n"
    )

    assert telemetry.config_disabled() is False
    monkeypatch.setenv(telemetry.PROFILE_ENV, "work")
    assert telemetry.config_disabled() is True


def test_loaded_options_opt_out_wins(sentry_events, telemetry_config_dir, monkeypatch):
    """Covers --config-file / --profile, which only the loaded options know about."""
    opts = config.Options()
    opts.telemetry = False
    monkeypatch.setattr(config.OPTIONS, "value", opts, raising=False)

    assert telemetry.config_disabled() is True
    assert telemetry.report_exception(raise_and_catch(RuntimeError("boom"))) is False


def test_unreadable_config_fails_closed(sentry_events, telemetry_config_dir):
    (telemetry_config_dir / "config.ini").write_text("not ini\n")

    assert telemetry.config_disabled() is True
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
ENTITLEMENT = "Ent1tlementTok3n"

FAKE_MODULE = """
def push_package(path, api_key):
    workspace = {slug!r}
    password = {password!r}
    raise FileNotFoundError(
        f"cannot read {{path}} with {{api_key}} via "
        "https://bob:pw@cloudsmith.acme.internal/api/ for {username}@{hostname} "
        "from https://dl.cloudsmith.io/{entitlement}/{slug}/repo/raw/x.tgz"
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
        SimpleNamespace(
            api_key=FILE_API_KEY, credential=None, api_config=None, telemetry=True
        ),
        raising=False,
    )

    module_path = project / "acme_tool.py"
    module_path.write_text(
        FAKE_MODULE.format(
            slug=SLUG,
            password=PASSWORD,
            username=USERNAME,
            hostname=HOSTNAME,
            entitlement=ENTITLEMENT,
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
        ENTITLEMENT,
        "bob:pw",
        "acme.internal",
        "acme-pkg",
    ],
)
def test_no_identifier_or_secret_anywhere(scrubbed_event, secret):
    assert secret.lower() not in json.dumps(scrubbed_event).lower()


def test_no_real_paths_or_machine_identity(scrubbed_event, anonymity_env, tmp_path):
    serialised = json.dumps(scrubbed_event)

    assert str(tmp_path) not in serialised
    assert str(anonymity_env.home) not in serialised


def test_home_paths_are_abbreviated(scrubbed_event):
    """Frame paths keep their shape; message paths keep only their root."""
    (exc,) = scrubbed_event["exception"]["values"]
    frame = exc["stacktrace"]["frames"][-1]

    assert frame["function"] == "push_package"
    assert frame["abs_path"] == "~/projects/tool/acme_tool.py"
    assert "cannot read ~/<path> with" in exc["value"]


def test_message_keeps_its_shape(scrubbed_event):
    (exc,) = scrubbed_event["exception"]["values"]

    assert exc["value"] == (
        "cannot read ~/<path> with [redacted] via "
        "https://[redacted]@<host>/<path> for <email> "
        "from https://dl.cloudsmith.io/<path>"
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
            "https://[redacted]@api.cloudsmith.io/<path>",
        ),
        ("https://api.cloudsmith.io/v1/", "https://api.cloudsmith.io/<path>"),
        ("https://api.cloudsmith.io/", "https://api.cloudsmith.io/"),
        ("https://dl.cloudsmith.com/x", "https://dl.cloudsmith.com/<path>"),
        ("https://cs.acme.internal/v1", "https://<host>/<path>"),
        ("https://evilcloudsmith.io/v1", "https://<host>/<path>"),
        (
            "see (https://api.cloudsmith.io/v1/x).",
            "see (https://api.cloudsmith.io/<path>).",
        ),
        ("https://[fe80::1]:8080/a", "https://<host>:8080/<path>"),
        (
            "HTTPSConnectionPool(host='10.0.0.5', port=443)",
            "HTTPSConnectionPool(host='<host>', port=443)",
        ),
        (
            "HTTPSConnectionPool(host='api.cloudsmith.io', port=443)",
            "HTTPSConnectionPool(host='api.cloudsmith.io', port=443)",
        ),
    ],
)
def test_hosts_and_url_credentials(text, expected):
    assert scrubber().scrub_message(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # Paths on Cloudsmith hosts carry slugs and entitlement tokens.
        (
            "GET https://dl.cloudsmith.io/AbCdEf123456/acme-org/repo/raw/p.tgz",
            "GET https://dl.cloudsmith.io/<path>",
        ),
        (
            "https://api.cloudsmith.io/v1/packages/acme/repo/?token=zzz",
            "https://api.cloudsmith.io/<path>",
        ),
        (
            "https://bucket.s3.amazonaws.com/x?X-Amz-Credential=AKIAABCDEFGHIJKLMNOP",
            "https://<host>/<path>",
        ),
        # Passwords containing "@" or "/".
        (
            "https://user:p@ss@proxy.acme.internal:3128",
            "https://[redacted]@<host>:3128",
        ),
        ("https://user:ab/cd@proxy.acme.internal", "https://[redacted]@<host>"),
        # Bare hosts, IPs, emails.
        (
            "Failed to resolve 'cs.acme.internal' ([Errno 8] nodename)",
            "Failed to resolve '<name>' ([Errno 8] nodename)",
        ),
        ("proxy.acme.internal:3128 refused", "<name>:3128 refused"),
        ("peer 10.1.2.3 and fe80::1ff:fe23:4567:890a", "peer <ip> and <ip>"),
        ("user bob.jones@acme.com not found", "user <email> not found"),
        # Credentials of any origin.
        (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.s",
            "Authorization: [redacted]",
        ),
        (
            "sent Bearer abc123def456 and AKIAABCDEFGHIJKLMNOP",
            "sent Bearer [redacted] and [redacted]",
        ),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig", "jwt [redacted]"),
        (
            '{"api_key": "s3cr3t", "password": "pw"} token=abc',
            '{"api_key": "[redacted]", "password": "[redacted]"} token=[redacted]',
        ),
        ("X-Api-Key: abcdef", "X-Api-Key: [redacted]"),
        (
            "sha 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "sha [redacted]",
        ),
        # Paths and file names outside the known prefixes.
        (
            "No such file: '/mnt/builds/acme-product/acme-product-2.0.rpm'",
            "No such file: '<path>'",
        ),
        ("open /mnt/builds/x.rpm now", "open <path> now"),
        ("open C:\\Builds\\acme\\x.rpm now", "open <path> now"),
        (
            "cannot push dist/acme-1.0.whl to acme-org/secret-repo",
            "cannot push <path> to <path>",
        ),
        ("missing acme-product-2.0.rpm", "missing <name>"),
    ],
)
def test_message_shapes_are_scrubbed(text, expected):
    assert scrubber().scrub_message(text) == expected


def test_message_user_roots_keep_only_the_root():
    s = scrubber(home=["/home/alice"], path_prefixes=[("/work/proj", "<cwd>")])

    assert s.scrub_message("open '/home/alice/a b.txt'") == "open '~/<path>'"
    assert s.scrub_message("in /work/proj/dist/x.whl") == "in <cwd>/<path>"


def test_message_install_paths_are_kept():
    s = scrubber(path_prefixes=[("/opt/py/lib/site-packages", "<site>")])

    text = "in /opt/py/lib/site-packages/cloudsmith_cli/core/rest.py line 3"
    assert s.scrub_message(text) == "in <site>/cloudsmith_cli/core/rest.py line 3"


@pytest.mark.parametrize(
    "text",
    [
        "'hint'",
        "'NoneType' object has no attribute 'foo'",
        "RestClient.request() got an unexpected keyword argument 'x'",
        "module 'os.path' has no attribute 'nope'",
        "Expecting value: line 1 column 1 (char 0)",
        "I/O operation on closed file.",
        "invalid literal for int() with base 10: 'abc'",
        "basic authentication failed, e.g. on version 3.11.4",
        "KeyError: 'x'",
        "Foo::bar at 12:30:45",
    ],
)
def test_ordinary_messages_survive(text):
    assert scrubber().scrub_message(text) == text


# --- Chained exceptions -----------------------------------------------------


class _FakeHttpResponse:
    status = 404
    reason = "Not Found"
    data = b'{"detail": "No repo acme-secret-repo", "email": "bob@acme.com"}'

    def getheaders(self):
        return {"Set-Cookie": "sessionid=SESSION-COOKIE-123"}


def test_chained_api_exceptions_send_no_server_text(sentry_events):
    """A bug while handling an API error must not leak the HTTP exchange.

    ``catch_raise_api_exception`` raises the CLI's ApiException inside the
    SDK's, so both are in the chain Sentry reports.
    """
    from cloudsmith_api.rest import ApiException as SdkApiException

    from cloudsmith_cli.core.api.exceptions import (
        ApiException,
        catch_raise_api_exception,
    )

    try:
        try:
            with catch_raise_api_exception():
                raise SdkApiException(http_resp=_FakeHttpResponse())
        except ApiException as exc:
            raise KeyError("hint") from exc
    except KeyError as exc:
        assert telemetry.report_exception(exc) is True

    (event,) = sentry_events
    values = {v["type"]: v for v in event["exception"]["values"]}
    assert values["KeyError"]["value"] == "'hint'"
    assert len(event["exception"]["values"]) == 3
    serialised = json.dumps(event)
    for leaked in (
        "SESSION-COOKIE",
        "bob@acme.com",
        "acme-secret-repo",
        "HTTP response",
    ):
        assert leaked not in serialised


def test_raw_http_dump_is_cut_from_any_message():
    s = scrubber()
    message = "(500)\nReason: x\nHTTP response headers: {'Set-Cookie': 'a'}"

    # pylint: disable=protected-access
    assert (
        telemetry._exception_message("other", "Err", message, s) == "(500)\nReason: x\n"
    )
