# Copyright 2026 Cloudsmith Ltd
"""Report unexpected CLI errors to Sentry, unless the user has opted out.

Only exceptions that escape every other handler reach here: click's own
errors and handled API errors never do. Reporting is on by default (including
in CI) and is turned off by either of:

* ``DO_NOT_TRACK`` - the cross-tool convention (https://consoledonottrack.com).
* ``CLOUDSMITH_NO_TELEMETRY`` - the tool-specific variable.

Anonymisation is enforced by :func:`scrub_event`, which *rebuilds* the event
from an allowlist rather than deleting known-bad fields, so anything new the
SDK starts collecting is dropped by default. Free text (exception messages and
paths) goes through :func:`scrub_text`.

Keep this module's imports light: it is loaded on the error path only, and
``sentry_sdk`` must only ever be imported inside :func:`_send`.
"""

import os
import platform
import re
import sys

import click

#: Production ingest DSN for the dedicated ``cloudsmith-cli`` Sentry project.
#: Not a secret: a DSN is a public, write-only ingest key, and every client
#: that reports to Sentry ships one. Abuse (event injection) is contained on
#: the Sentry side by the project's rate limit and inbound filters; if the key
#: is abused, rotate it in Sentry and ship the new DSN.
DSN = "https://0a93d7eb45c68ec0116ff0938d94002e@o89590.ingest.us.sentry.io/4512180867104768"
#: Developer override for the DSN (e.g. a test project or a local catcher).
#: Set it empty to disable sending.
DSN_ENV = "CLOUDSMITH_TELEMETRY_DSN"

NO_TELEMETRY_ENV = "CLOUDSMITH_NO_TELEMETRY"
DO_NOT_TRACK_ENV = "DO_NOT_TRACK"
OPT_OUT_ENVS = (DO_NOT_TRACK_ENV, NO_TELEMETRY_ENV)
_TRUTHY_ENV_VALUES = ("1", "true", "yes")

#: Upper bound on how long a failing command waits for the report to send.
FLUSH_TIMEOUT_SECONDS = 2.0
MAX_MESSAGE_LENGTH = 1024

#: Hosts that may appear in reports; any other host (custom/self-hosted API,
#: proxies, internal registries) is replaced.
_ALLOWED_HOST_SUFFIXES = ("cloudsmith.io", "cloudsmith.com")
#: Env vars whose values are treated as secrets wherever they appear.
_SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH", re.IGNORECASE)
_MIN_SECRET_LENGTH = 8
#: Usernames/hostnames shorter than this are not scrubbed as words, to avoid
#: mangling ordinary text.
_MIN_IDENTIFIER_LENGTH = 3

_TOP_LEVEL_KEYS = (
    "event_id",
    "timestamp",
    "level",
    "platform",
    "release",
    "environment",
    "sdk",
)
_TAG_KEYS = ("command", "channel", "arch", "frozen")
_FRAME_KEYS = ("function", "module", "lineno")
_MECHANISM_KEYS = ("type", "exception_id", "parent_id", "source", "is_exception_group")

#: Test seam: a ``sentry_sdk.transport.Transport`` instance to use instead of
#: HTTP.
_transport = None


def format_exception_summary(exc: BaseException) -> str:
    """Return a one-line ``Type: message`` summary of ``exc``."""
    return f"{type(exc).__name__}: {exc}"


def telemetry_disabled(env: "os._Environ[str] | dict[str, str] | None" = None) -> bool:
    """Tell whether the user has opted out of error reporting.

    Either opt-out variable set to ``1``/``true``/``yes`` (case-insensitive)
    disables reporting. Any other value, or unset, leaves it on.
    """
    env = os.environ if env is None else env
    return any(
        env.get(name, "").strip().lower() in _TRUTHY_ENV_VALUES for name in OPT_OUT_ENVS
    )


def get_dsn(env: "os._Environ[str] | dict[str, str] | None" = None) -> str:
    """Return the DSN to report to; empty means do not report."""
    env = os.environ if env is None else env
    if DSN_ENV in env:
        return env[DSN_ENV].strip()
    return DSN


def report_exception(exc: BaseException) -> bool:
    """Report ``exc`` unless opted out; return whether an event was sent.

    Never raises - not even ``KeyboardInterrupt`` during the flush wait - and
    never waits longer than :data:`FLUSH_TIMEOUT_SECONDS`: a failure while
    reporting must not change the outcome of the command that is failing.
    """
    try:
        if telemetry_disabled():
            return False
        dsn = get_dsn()
        if not dsn:
            return False
        return _send(exc, dsn)
    except BaseException:  # pylint: disable=broad-exception-caught
        return False


def _send(exc: BaseException, dsn: str) -> bool:
    """Build a locked-down, single-use Sentry client and send one event."""
    import sentry_sdk

    from . import installation, version

    channel = _safe(installation.detect_channel, default=installation.CHANNEL_UNKNOWN)
    client = sentry_sdk.Client(
        dsn=dsn,
        transport=_transport,
        release=f"cloudsmith-cli@{_safe(version.get_version, default='unknown')}",
        environment=get_environment(),
        before_send=scrub_event,
        # Do not hook logging, threading, atexit, sys.excepthook or any
        # installed library; this client only ever sends the one event below.
        default_integrations=False,
        auto_enabling_integrations=False,
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=False,
        max_breadcrumbs=0,
        auto_session_tracking=False,
        send_client_reports=False,
        # "" rather than None: None makes the SDK fill in the hostname.
        server_name="",
        shutdown_timeout=FLUSH_TIMEOUT_SECONDS,
    )
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_client(client)
            scope.set_tags(
                {
                    "command": command_path(exc) or "<unknown>",
                    "channel": channel,
                    "arch": platform.machine().lower() or "unknown",
                    "frozen": str(bool(getattr(sys, "frozen", False))).lower(),
                }
            )
            scope.set_context(
                "os", {"name": platform.system(), "version": platform.release()}
            )
            scope.set_context(
                "runtime",
                {
                    "name": platform.python_implementation(),
                    "version": platform.python_version(),
                },
            )
            event_id = scope.capture_exception(exc)
    finally:
        client.close(timeout=FLUSH_TIMEOUT_SECONDS)
    return event_id is not None


def get_environment(package_file=None, frozen=None):
    """Return ``development`` for a source checkout, else ``production``.

    Frozen builds and wheels installed into site-/dist-packages are releases;
    anything imported from elsewhere is an editable install or a checkout, so
    developers' errors stay out of production triage.
    """
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        return "production"
    path = (package_file or os.path.abspath(__file__)).replace("\\", "/")
    installed = "/site-packages/" in path or "/dist-packages/" in path
    return "production" if installed else "development"


def _safe(func, default):
    try:
        return func()
    except Exception:  # pylint: disable=broad-exception-caught
        return default


def command_path(exc: BaseException) -> str | None:
    """Return the canonical command path (e.g. ``repositories gpg create``).

    The click context has been torn down by the time the exception reaches
    ``AliasGroup.main``, so find the deepest one still referenced by the
    traceback. Only command *names* are used - they are defined in code and
    resolved from aliases - never the program name or any argument.
    """
    ctx = None
    tb = exc.__traceback__
    while tb is not None:
        frame_locals = tb.tb_frame.f_locals
        for name in ("ctx", "self"):
            if isinstance(frame_locals.get(name), click.Context):
                ctx = frame_locals[name]
                break
        tb = tb.tb_next

    names = []
    while ctx is not None and ctx.parent is not None:
        if ctx.command.name:
            names.append(ctx.command.name)
        ctx = ctx.parent
    return " ".join(reversed(names)) or None


# --- Scrubbing --------------------------------------------------------------


def scrub_event(event, hint=None):  # pylint: disable=unused-argument
    """``before_send`` hook: return an allowlisted, scrubbed copy of ``event``.

    Fails closed: if anything goes wrong, the event is dropped (``None``).
    """
    try:
        return _rebuild_event(event, Scrubber.from_environment())
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _rebuild_event(event, scrubber):
    out = {key: event[key] for key in _TOP_LEVEL_KEYS if key in event}

    values = [
        _rebuild_exception(value, scrubber)
        for value in (event.get("exception") or {}).get("values") or []
    ]
    if values:
        out["exception"] = {"values": values}

    tags = event.get("tags") or {}
    out["tags"] = {
        key: scrubber.scrub(str(tags[key])) for key in _TAG_KEYS if key in tags
    }

    contexts = event.get("contexts") or {}
    out["contexts"] = {
        name: {
            key: str(contexts[name][key])
            for key in ("name", "version")
            if key in contexts[name]
        }
        for name in ("os", "runtime")
        if isinstance(contexts.get(name), dict)
    }
    return out


def _rebuild_exception(value, scrubber):
    out = {
        "type": scrubber.scrub(str(value.get("type") or "")),
        "module": value.get("module"),
        "value": scrubber.scrub(str(value.get("value") or ""))[:MAX_MESSAGE_LENGTH],
    }

    mechanism = value.get("mechanism") or {}
    out["mechanism"] = {
        key: mechanism[key] for key in _MECHANISM_KEYS if key in mechanism
    }
    # It escaped every handler in the CLI, whatever the SDK inferred.
    out["mechanism"]["handled"] = False
    out["mechanism"].setdefault("type", "cloudsmith_cli")

    frames = ((value.get("stacktrace") or {}).get("frames")) or []
    out["stacktrace"] = {"frames": [_rebuild_frame(f, scrubber) for f in frames]}
    return out


def _rebuild_frame(frame, scrubber):
    out = {key: frame[key] for key in _FRAME_KEYS if key in frame}
    for key in ("filename", "abs_path"):
        if frame.get(key):
            out[key] = scrubber.scrub(str(frame[key]))
    out["in_app"] = str(frame.get("module") or "").startswith("cloudsmith_cli")
    # Deliberately dropped: vars (locals), context_line, pre_context,
    # post_context - the source and values around each frame.
    return out


class Scrubber:
    """Replace identifying or secret substrings in free text.

    Applied in order: known secret values, URL credentials, non-Cloudsmith
    hostnames, filesystem prefixes (most specific first), then the OS username
    and machine hostname as whole words.
    """

    def __init__(
        self,
        *,
        home=None,
        path_prefixes=(),
        usernames=(),
        hostnames=(),
        secrets=(),
        case_insensitive=False,
    ):
        flags = re.IGNORECASE if case_insensitive else 0
        self.secrets = sorted(
            {s for s in secrets if s and len(s) >= _MIN_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

        prefixes = {}
        for prefix, token in path_prefixes:
            if _is_specific_path(prefix):
                prefixes.setdefault(_normalise_path(prefix), token)
        # Home is always scrubbed, even when shallow (e.g. /root).
        for prefix in home or ():
            if prefix and _normalise_path(prefix) not in ("", "/"):
                prefixes[_normalise_path(prefix)] = "~"
        self.paths = [
            (_path_pattern(prefix, flags), token)
            for prefix, token in sorted(
                prefixes.items(), key=lambda item: len(item[0]), reverse=True
            )
        ]

        self.words = [
            (_word_pattern(word), token)
            for words, token in ((usernames, "<user>"), (hostnames, "<host>"))
            for word in sorted(
                {w for w in words if w and len(w) >= _MIN_IDENTIFIER_LENGTH},
                key=len,
                reverse=True,
            )
        ]

    @classmethod
    def from_environment(cls):
        """Build a scrubber for the current user, machine and credentials."""
        import tempfile

        home = os.path.expanduser("~")
        prefixes = [
            (sys.prefix, "<prefix>"),
            (sys.exec_prefix, "<prefix>"),
            (sys.base_prefix, "<python>"),
            (_safe(tempfile.gettempdir, default=""), "<tmp>"),
            (_safe(os.getcwd, default=""), "<cwd>"),
            (_package_root(), "<site>"),
        ]
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            prefixes.append((bundle, "<app>"))

        hostname = _safe(_hostname, default="")
        return cls(
            home=[home, _realpath(home)],
            path_prefixes=prefixes + [(_realpath(p), t) for p, t in prefixes],
            usernames=[_safe(_username, default="")]
            + [os.environ.get(k, "") for k in ("USER", "USERNAME", "LOGNAME")],
            hostnames=[hostname, hostname.split(".")[0]],
            secrets=_secret_values(),
            case_insensitive=os.name == "nt" or sys.platform == "darwin",
        )

    def scrub(self, text):
        if not text:
            return text
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        text = _URL_USERINFO.sub("[redacted]@", text)
        text = _HOST_REFERENCE.sub(_replace_host, text)
        for pattern, token in self.paths:
            text = pattern.sub(token, text)
        for pattern, token in self.words:
            text = pattern.sub(token, text)
        return text


def scrub_text(text):
    """Scrub ``text`` for the current environment; see :class:`Scrubber`."""
    return Scrubber.from_environment().scrub(text)


_URL_USERINFO = re.compile(r"(?<=://)[^/\s@:]+(?::[^/\s@]*)?@")
#: A host in a URL (``https://[user@]host``) or a urllib3 message
#: (``host='host'``).
_HOST_REFERENCE = re.compile(
    r"(?P<lead>://(?:[^/\s@]*@)?|host=['\"])(?P<host>[A-Za-z0-9.-]+)"
)


def _replace_host(match):
    host = match.group("host").lower().rstrip(".")
    if any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
        return match.group(0)
    return match.group("lead") + "<host>"


def _realpath(path):
    """``os.path.realpath`` that never raises (paths may not exist)."""
    try:
        return os.path.realpath(path) if path else path
    except (OSError, ValueError):
        return path


def _normalise_path(path):
    return path.replace("\\", "/").rstrip("/")


def _is_specific_path(path):
    """True for an absolute path at least two levels deep (not /usr, /tmp)."""
    if not path or not os.path.isabs(path):
        return False
    parts = [p for p in re.split(r"[\\/]", _normalise_path(path)) if p]
    if parts and parts[0].endswith(":"):  # Windows drive letter
        parts = parts[1:]
    return len(parts) >= 2


def _path_pattern(prefix, flags):
    """Match ``prefix`` with either separator, ending at a path boundary."""
    parts = re.split(r"/", prefix)
    body = r"[\\/]".join(re.escape(p) for p in parts)
    return re.compile(body + r"(?![\w.-])", flags)


def _word_pattern(word):
    return re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", re.IGNORECASE)


def _package_root():
    """The directory containing the ``cloudsmith_cli`` package."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _username():
    import getpass

    return getpass.getuser()


def _hostname():
    import socket

    return socket.gethostname()


def _secret_values():
    """Values that must never appear: credential env vars and live credentials."""
    values = [
        value
        for name, value in os.environ.items()
        if _SECRET_ENV_NAME.search(name) and name != DSN_ENV
    ]
    # The credential the CLI actually resolved, which may have come from a
    # file or the keyring rather than the environment. Read it only if the
    # config module is already loaded, so this never imports more code.
    config = sys.modules.get("cloudsmith_cli.cli.config")
    opts = getattr(getattr(config, "OPTIONS", None), "value", None)
    if opts is not None:
        for get in (
            lambda: opts.api_key,
            lambda: opts.credential.api_key,
            lambda: opts.api_config.api_key.get("X-Api-Key"),
            lambda: opts.api_config.headers.get("Authorization", "").split(" ", 1)[-1],
        ):
            value = _safe(get, default=None)
            if isinstance(value, str):
                values.append(value)
    return values
