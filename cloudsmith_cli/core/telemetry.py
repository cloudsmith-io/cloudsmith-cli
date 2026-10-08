# Copyright 2026 Cloudsmith Ltd
"""Report unexpected CLI errors to Sentry, unless the user has opted out.

Only exceptions that escape every other handler reach here: click's own
errors and handled API errors never do. Reporting is on by default (including
in CI) and is turned off by any of:

* ``DO_NOT_TRACK`` - the cross-tool convention (https://consoledonottrack.com).
* ``CLOUDSMITH_NO_TELEMETRY`` - the tool-specific variable.
* ``telemetry = false`` in config.ini - so the choice survives a new shell.

Any one opt-out wins; ``telemetry = true`` does not override the env vars.

Anonymisation is enforced by :func:`scrub_event`, which *rebuilds* the event
from an allowlist rather than deleting known-bad fields, so anything new the
SDK starts collecting is dropped by default. Exception messages go through
:meth:`Scrubber.scrub_message`; frame paths through :meth:`Scrubber.scrub`.
Messages of SDK exceptions (raw HTTP responses) and of handled API errors
(server text) are never sent, even when they appear only in the chain.

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


PROFILE_ENV = "CLOUDSMITH_PROFILE"


def config_disabled() -> bool:
    """Tell whether ``telemetry = false`` is set in config.ini.

    Checked two ways, and either one saying ``false`` wins:

    * the options the command loaded, which honour ``--config-file`` and
      ``--profile`` - but only exist if the command loads config at all;
    * a fresh read of config.ini (``[default]`` plus ``$CLOUDSMITH_PROFILE``),
      which covers commands that never load config or failed before doing so.

    Fails closed: if the config cannot be read we cannot confirm the user has
    not opted out, so we do not report.
    """
    try:
        from ..cli import config

        opts = getattr(config.OPTIONS, "value", None)
        if opts is not None and opts.telemetry is False:
            return True

        probe = config.Options()
        config.ConfigReader.load_config(probe, profile=os.environ.get(PROFILE_ENV))
        return probe.telemetry is False
    except Exception:  # pylint: disable=broad-exception-caught
        return True


def get_dsn(env: "os._Environ[str] | dict[str, str] | None" = None) -> str:
    """Return the DSN to report to; empty means do not report."""
    env = os.environ if env is None else env
    if DSN_ENV in env:
        return env[DSN_ENV].strip()
    return DSN


#: Class attribute that marks an exception type as a user error rather than a
#: CLI bug. Set it to ``False`` on the class; subclasses inherit it.
REPORTABLE_ATTR = "report_to_telemetry"


def is_reportable(exc: BaseException) -> bool:
    """Tell whether ``exc`` is a CLI bug worth reporting.

    Exception types that represent a user error (e.g. a missing 2FA code) set
    ``report_to_telemetry = False``. Checked by attribute rather than by
    importing the types, so this module stays light on the error path.
    """
    return getattr(exc, REPORTABLE_ATTR, True) is not False


def report_exception(exc: BaseException) -> bool:
    """Report ``exc`` unless opted out; return whether an event was sent.

    Never raises - not even ``KeyboardInterrupt`` during the flush wait - and
    never waits longer than :data:`FLUSH_TIMEOUT_SECONDS`: a failure while
    reporting must not change the outcome of the command that is failing.
    """
    try:
        if not is_reportable(exc):
            return False
        if telemetry_disabled() or config_disabled():
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
    module = str(value.get("module") or "")
    type_name = str(value.get("type") or "")
    out = {
        "type": scrubber.scrub(type_name),
        "module": module or None,
        "value": _exception_message(
            module, type_name, str(value.get("value") or ""), scrubber
        ),
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


#: Sentry reports every exception in the ``__context__``/``__cause__`` chain, so
#: these rules apply to exceptions the CLI handled as well as the one that
#: escaped.
_SDK_MODULE_PREFIX = "cloudsmith_api"
_CLI_MODULE_PREFIX = "cloudsmith_cli"
#: The generated SDK's ``str()`` appends the raw HTTP exchange.
_RAW_HTTP_DUMP = re.compile(r"HTTP response (?:headers|body):", re.IGNORECASE)


def _exception_message(module, type_name, message, scrubber):
    """Return the part of an exception's message that may be sent.

    * ``cloudsmith_api`` (generated SDK) exceptions: nothing. Their message
      is the raw HTTP response - headers (cookies, auth echoes) and body
      (emails, slugs, any server text).
    * The CLI's own ``ApiException``: nothing. The SDK takes the message from
      its ``detail`` attribute, which is server-supplied text naming
      workspaces, repositories and packages.
    * Anything else: the scrubbed message, cut before any raw HTTP dump.
    """
    if module == _SDK_MODULE_PREFIX or module.startswith(_SDK_MODULE_PREFIX + "."):
        return ""
    if type_name == "ApiException" and module.startswith(_CLI_MODULE_PREFIX):
        return ""
    message = _RAW_HTTP_DUMP.split(message, maxsplit=1)[0]
    return scrubber.scrub_message(message)[:MAX_MESSAGE_LENGTH]


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
    """Replace identifying or secret substrings in text.

    :meth:`scrub` handles code locations (frame paths) and tags: known secret
    values, filesystem prefixes (most specific first), then the OS username
    and machine hostname as whole words. :meth:`scrub_message` additionally
    removes anything shaped like a credential, URL path, host, email, IP,
    file name or path from free text.
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
        """Scrub a code location or tag: secrets, path prefixes, identity.

        Used for frame paths, which must stay readable (they point at code,
        not user data), so no generic name or path collapsing is applied.
        """
        if not text:
            return text
        text = self._redact_secrets(text)
        text = self._replace_prefixes(text)
        return self._replace_words(text)

    def scrub_message(self, text):
        """Scrub free text (an exception message) for sending.

        Messages embed whatever the failing code was handling, so beyond the
        known values this removes anything *shaped* like a credential, URL
        path, email, IP, hostname, file name or path. Order matters: each
        step sees the placeholders left by the earlier ones.
        """
        if not text:
            return text
        text = self._redact_secrets(text)
        # URLs first: their query strings are dropped whole, not piecemeal.
        text = _URL.sub(_replace_url, text)
        for pattern, replacement in _CREDENTIAL_PATTERNS:
            text = pattern.sub(replacement, text)
        text = _LONG_TOKEN.sub(_replace_long_token, text)
        text = _EMAIL.sub("<email>", text)
        text = _HOST_ASSIGNMENT.sub(_replace_host_assignment, text)
        text = _IPV4.sub("<ip>", text)
        text = _IPV6.sub("<ip>", text)
        text = self._replace_prefixes(text)
        text = _QUOTED_PATH.sub(_replace_quoted_path, text)
        text = _ABSOLUTE_PATH.sub(_replace_absolute_path, text)
        text = _RELATIVE_PATH.sub(_replace_relative_path, text)
        text = _DOTTED_NAME.sub(_replace_dotted_name, text)
        return self._replace_words(text)

    def _redact_secrets(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text

    def _replace_prefixes(self, text):
        for pattern, token in self.paths:
            text = pattern.sub(token, text)
        return text

    def _replace_words(self, text):
        for pattern, token in self.words:
            text = pattern.sub(token, text)
        return text


def scrub_text(text):
    """Scrub free ``text`` for the current environment; see :class:`Scrubber`."""
    return Scrubber.from_environment().scrub_message(text)


# --- Message rules ----------------------------------------------------------

_REDACTED = "[redacted]"

#: Shapes of credentials that are not one of the known secret values.
_CREDENTIAL_PATTERNS = (
    # An Authorization header, whatever its scheme: the whole value.
    (
        re.compile(
            r"(?i)(\b(?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?)[^\"'\n,}]+"
        ),
        r"\1" + _REDACTED,
    ),
    # A scheme-prefixed token outside a header. The digit lookahead keeps
    # prose such as "basic authentication" intact.
    (
        re.compile(r"(?i)\b(bearer|basic)\s+(?=[\w.~+/=-]*\d)[\w.~+/=-]+"),
        r"\1 " + _REDACTED,
    ),
    # JSON Web Tokens.
    (re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*"), _REDACTED),
    # AWS access key IDs.
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), _REDACTED),
    # name=value / name: value / "name": "value" for credential-like names,
    # but not exception names ("KeyError: ...").
    (
        re.compile(
            r"(?i)(?<![\w-])(?![\w-]*(?:error|exception)\b)"
            r"([\w-]*(?:api[_-]?key|access[_-]?key|private[_-]?key|token|secret"
            r"|passw(?:or)?d|pwd|credential|signature|auth)[\w-]*"
            r"[\"']?\s*[=:]\s*[\"']?)"
            r"[^\s\"'&,;}\[\]]+"  # "[" so an earlier [redacted] is not re-hit
        ),
        r"\1" + _REDACTED,
    ),
)

#: Long opaque strings: API keys, hashes, encoded tokens.
_LONG_TOKEN = re.compile(r"(?<![\w+=-])[A-Za-z0-9+=_-]{32,}(?![\w+=-])")


def _replace_long_token(match):
    token = match.group(0)
    if re.fullmatch(r"[0-9a-fA-F]+", token):
        return _REDACTED
    has_mixed = (
        any(c.isdigit() for c in token)
        and any(c.islower() for c in token)
        and any(c.isupper() for c in token)
    )
    return _REDACTED if has_mixed else token


#: A URL, up to whitespace or a quote/angle bracket.
_URL = re.compile(r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*)://(?P<rest>[^\s'\"<>]*)")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _replace_url(match):
    """Keep scheme, an allowed host and the port; drop everything else.

    The path and query are dropped even on Cloudsmith hosts: they carry
    workspace/repository/package slugs and entitlement tokens. Userinfo runs
    to the *last* ``@`` so that passwords containing ``@`` or ``/`` are
    redacted whole (failing safe on the rare URL with ``@`` in its path).
    """
    rest = match.group("rest")
    stripped = rest.rstrip(_URL_TRAILING_PUNCTUATION)
    trailing, rest = rest[len(stripped) :], stripped

    userinfo = ""
    if "@" in rest:
        userinfo = _REDACTED + "@"
        rest = rest.rsplit("@", 1)[1]

    end = min((i for i in (rest.find(c) for c in "/?#") if i != -1), default=len(rest))
    authority, tail = rest[:end], rest[end:]

    host, port = authority, ""
    if authority.startswith("["):  # IPv6 literal
        host, _, after = authority.partition("]")
        host += "]"
        port = after[1:] if after.startswith(":") else ""
    elif ":" in authority:
        host, port = authority.rsplit(":", 1)
    port = f":{port}" if port.isdigit() else ""

    if host and not _is_allowed_host(host):
        host = "<host>"
    path = "/<path>" if tail.strip("/") else tail
    return f"{match.group('scheme')}://{userinfo}{host}{port}{path}{trailing}"


def _is_allowed_host(host):
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES)


_EMAIL = re.compile(r"[\w.+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}")

#: urllib3's ``HTTPSConnectionPool(host='...')``.
_HOST_ASSIGNMENT = re.compile(r"(?P<lead>\bhost=['\"])(?P<host>[^'\"]+)")


def _replace_host_assignment(match):
    if _is_allowed_host(match.group("host")):
        return match.group(0)
    return match.group("lead") + "<host>"


_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
#: Full or ``::``-compressed IPv6. Requires a hex digit and not being glued to
#: a word, so ``Foo::bar`` and a lone ``::`` are left alone.
_IPV6 = re.compile(
    r"(?i)(?<![\w:])"
    r"(?=[0-9a-f:]*::|(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4})"
    r"(?=[0-9a-f:]*[0-9a-f])"
    r"(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}"
    r"(?![\w:])"
)

#: Path-prefix placeholders. Install locations are kept intact (they hold
#: code, not user data); under user locations only the root is kept.
_KEPT_ROOTS = ("<prefix>", "<python>", "<site>", "<app>")
_USER_ROOTS = ("~", "<cwd>", "<tmp>")
_PATH_ROOT = r"~|<(?:prefix|python|site|app|cwd|tmp)>|[A-Za-z]:"

#: A quoted string containing a path separator (and not a URL): a path, or a
#: slug such as ``'owner/repo'``.
_QUOTED_PATH = re.compile(r"(?P<q>['\"])(?P<body>[^'\"\n]*[\\/][^'\"\n]*)(?P=q)")
#: An unquoted absolute path, optionally under a placeholder root.
_ABSOLUTE_PATH = re.compile(
    r"(?<![\w.~<>:/\\-])(?P<root>" + _PATH_ROOT + r")?"
    r"(?P<sep>[\\/])(?P<rest>[^\s'\"<>|,;()\[\]{}]+)"
)
#: An unquoted relative path or slug: ``dist/pkg.whl``, ``owner/repo``.
_RELATIVE_PATH = re.compile(r"(?<![\w.~<>:/\\-])[\w.-]+(?:[\\/][\w.-]+)+[\\/]?")
#: Common prose that looks like a relative path.
_NOT_PATHS = frozenset(
    ("i/o", "and/or", "n/a", "w/o", "tcp/ip", "read/write", "input/output")
)


def _collapse_path(path):
    for root in _KEPT_ROOTS:
        if path.startswith(root):
            return path
    for root in _USER_ROOTS:
        if path.startswith(root) and path[len(root) : len(root) + 1] in ("/", "\\"):
            return root + path[len(root)] + "<path>"
    return "<path>"


def _replace_quoted_path(match):
    body = match.group("body")
    if "://" in body or body.strip().lower() in _NOT_PATHS:
        return match.group(0)
    return match.group("q") + _collapse_path(body.strip()) + match.group("q")


def _replace_absolute_path(match):
    root = match.group("root") or ""
    return _collapse_path(root + match.group("sep") + match.group("rest"))


def _replace_relative_path(match):
    if match.group(0).lower() in _NOT_PATHS:
        return match.group(0)
    return "<path>"


#: A dotted name - a hostname or a file name (``cs.acme.internal``,
#: ``acme-pkg-1.0.whl``). The last label must start with a letter and be two
#: or more characters, so versions (``3.11``) and ``e.g.`` are left alone.
_DOTTED_NAME = re.compile(
    r"(?<![\w.@-])"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9]"
    r"(?![\w-]|\.\w|\()"  # not mid-name, and not a call: ``Client.request()``
)
#: Extensions of code files, whose names point at code rather than user data.
_CODE_EXTENSIONS = frozenset(("py", "pyc", "pyi", "pyd", "so", "dll", "dylib"))


def _replace_dotted_name(match):
    name = match.group(0)
    if _is_allowed_host(name) or name.rsplit(".", 1)[-1].lower() in _CODE_EXTENSIONS:
        return name
    # Python names - ``os.path``, ``json.decoder.JSONDecodeError`` - are code.
    if name in sys.modules or name.rsplit(".", 1)[0] in sys.modules:
        return name
    return "<name>"


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
