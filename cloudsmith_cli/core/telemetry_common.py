# Copyright 2026 Cloudsmith Ltd
"""Helpers shared by error reporting, update checks and usage telemetry.

Keep this module's imports light (no ``requests``, ``ssl`` or ``urllib3``):
it is imported on every command.
"""

import enum
import os
import sys
from urllib.parse import urlsplit

NO_TELEMETRY_ENV = "CLOUDSMITH_NO_TELEMETRY"
DO_NOT_TRACK_ENV = "DO_NOT_TRACK"
OPT_OUT_ENVS = (DO_NOT_TRACK_ENV, NO_TELEMETRY_ENV)
_TRUTHY_ENV_VALUES = ("1", "true", "yes")

#: ``CLOUDSMITH_TELEMETRY`` turns both kinds of telemetry (error reports and
#: usage events) on or off, or to ``log``, which prints what would be sent to
#: stderr instead of sending it. The two variables below do the same for one
#: kind and win over it. All three win over ``CLOUDSMITH_NO_TELEMETRY`` and
#: ``DO_NOT_TRACK``, so telemetry can be off for every tool but on for this
#: one.
MODE_ENV = "CLOUDSMITH_TELEMETRY"
USAGE_REPORTING_ENV = "CLOUDSMITH_TELEMETRY_USAGE_REPORTING"
ERROR_REPORTING_ENV = "CLOUDSMITH_TELEMETRY_ERROR_REPORTING"
MODE_ENVS = (MODE_ENV, USAGE_REPORTING_ENV, ERROR_REPORTING_ENV)
MODE_LOG = "log"
#: Usage telemetry's switch for a stored install ID; here so the CLI can
#: check its value without importing ``core.usage``.
INSTALL_ID_ENV = "CLOUDSMITH_TELEMETRY_INSTALL_ID"

#: The config.ini keys that match the variables above.
CONFIG_KEY = "telemetry"
USAGE_REPORTING_CONFIG_KEY = "telemetry_usage_reporting"
ERROR_REPORTING_CONFIG_KEY = "telemetry_error_reporting"
CONFIG_KEYS = (CONFIG_KEY, USAGE_REPORTING_CONFIG_KEY, ERROR_REPORTING_CONFIG_KEY)
#: The config.ini key that matches ``CLOUDSMITH_TELEMETRY_INSTALL_ID`` (on/off).
INSTALL_ID_CONFIG_KEY = "telemetry_install_id"
#: The source of a mode that config.ini could not confirm (it fails closed).
CONFIG_UNREADABLE = "unreadable config.ini"

#: On/off values, also accepted by ``CLOUDSMITH_TELEMETRY_INSTALL_ID``.
SWITCH_ON_VALUES = ("enable", "enabled", "on", "true", "1", "yes")
SWITCH_OFF_VALUES = ("disable", "disabled", "off", "false", "0", "no")


class Mode(enum.Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    LOG = "log"


class Kind(enum.Enum):
    """The two kinds of telemetry, each with its own mode."""

    USAGE = "usage"
    ERRORS = "errors"


#: The variable and config.ini key that set one kind only.
_KIND_ENV = {Kind.USAGE: USAGE_REPORTING_ENV, Kind.ERRORS: ERROR_REPORTING_ENV}
_KIND_CONFIG_KEY = {
    Kind.USAGE: USAGE_REPORTING_CONFIG_KEY,
    Kind.ERRORS: ERROR_REPORTING_CONFIG_KEY,
}


def _env_value(env, name):
    return (os.environ if env is None else env).get(name, "").strip().lower()


def parse_switch(value: str) -> bool | None:
    """``True``/``False`` for an on/off value, ``None`` for anything else."""
    value = value.strip().lower()
    if value in SWITCH_ON_VALUES:
        return True
    if value in SWITCH_OFF_VALUES:
        return False
    return None


def parse_mode(value: "str | bool | None") -> Mode | None:
    """The mode an env var or config.ini value names, or ``None``.

    ``None`` for an unset, empty or unrecognised value. A ``bool`` (set in
    code, as tests do) is enabled or disabled.
    """
    if isinstance(value, bool):
        return Mode.ENABLED if value else Mode.DISABLED
    if not isinstance(value, str):
        return None
    if value.strip().lower() == MODE_LOG:
        return Mode.LOG
    switch = parse_switch(value)
    if switch is None:
        return None
    return Mode.ENABLED if switch else Mode.DISABLED


def is_unrecognised(value: "str | bool | None", *, takes_log: bool = True) -> bool:
    """Tell whether ``value`` is set but not a value the CLI recognises.

    The CLI warns about such a value and ignores it.
    """
    if value is None or isinstance(value, bool) or not str(value).strip():
        return False
    if takes_log:
        return parse_mode(value) is None
    return parse_switch(value) is None


def unrecognised(
    name: str, env: "os._Environ[str] | dict[str, str] | None" = None
) -> bool:
    """Tell whether the variable ``name`` is set to a value that is ignored."""
    return is_unrecognised(_env_value(env, name), takes_log=name in MODE_ENVS)


def env_mode(
    kind: Kind, env: "os._Environ[str] | dict[str, str] | None" = None
) -> tuple[Mode | None, str | None]:
    """The mode the environment variables set for ``kind``, and the variable.

    In order: the variable for ``kind`` (``CLOUDSMITH_TELEMETRY_USAGE_REPORTING``
    or ``CLOUDSMITH_TELEMETRY_ERROR_REPORTING``), ``CLOUDSMITH_TELEMETRY``,
    ``CLOUDSMITH_NO_TELEMETRY``, ``DO_NOT_TRACK``. An empty or unrecognised
    value is ignored. The opt-out variables only count when set to
    ``1``/``true``/``yes``; any other value cannot turn telemetry on.
    ``(None, None)`` when none of them decides.
    """
    for name in (_KIND_ENV[kind], MODE_ENV):
        mode = parse_mode(_env_value(env, name))
        if mode is not None:
            return mode, name
    for name in (NO_TELEMETRY_ENV, DO_NOT_TRACK_ENV):
        if _env_value(env, name) in _TRUTHY_ENV_VALUES:
            return Mode.DISABLED, name
    return None, None


class Send(enum.Flag):
    """What a command may send. ``ALL`` is the default for every command.

    A command's policy only narrows what is sent: the user's opt-outs and
    every other rule still apply on top of it.
    """

    NONE = 0
    #: Sentry reports of unexpected exceptions.
    ERRORS = enum.auto()
    #: The end-of-run usage event.
    USAGE = enum.auto()
    ALL = ERRORS | USAGE


_POLICY_ATTR = "__cloudsmith_telemetry__"


def send(policy: Send):
    """Set what a command (or a group and every command under it) may send.

    Works above or below ``@<group>.command()``; below it, put it directly
    under that line. The policy nearest the command that runs wins.
    """
    if not isinstance(policy, Send):
        raise TypeError(f"send() takes a telemetry policy, not {policy!r}")

    def mark(f):
        target = getattr(f, "callback", None) or f
        setattr(target, _POLICY_ATTR, policy)
        return f

    return mark


def declared_policy(command) -> "Send | None":
    """The policy set on a Click command or its callback, if any."""
    for obj in (command, getattr(command, "callback", None)):
        policy = getattr(obj, _POLICY_ATTR, None)
        if isinstance(policy, Send):
            return policy
    return None


def resolve_policy(ctx) -> Send:
    """The policy nearest ``ctx``'s command, walking up to the root."""
    while ctx is not None:
        policy = declared_policy(getattr(ctx, "command", None))
        if policy is not None:
            return policy
        ctx = getattr(ctx, "parent", None)
    return Send.ALL


PROFILE_ENV = "CLOUDSMITH_PROFILE"
CONFIG_FILE_ENV = "CLOUDSMITH_CONFIG_FILE"

#: Hosts whose API traffic may be measured; any other host (self-hosted,
#: proxies, internal registries) never sends usage telemetry.
CLOUDSMITH_HOST_SUFFIXES = ("cloudsmith.io", "cloudsmith.com")


def read_config_file():
    """Read config.ini afresh, with the file and profile the command used.

    If the command loaded config, that is its ``--config-file`` and
    ``--profile`` (which Click already fills from the environment). Otherwise
    it is ``$CLOUDSMITH_CONFIG_FILE`` and ``$CLOUDSMITH_PROFILE``, as the CLI
    would read them. Returns new options holding what the files set. Covers
    commands that never load config or failed before doing so. Raises if a
    file cannot be read; callers fail closed.
    """
    from ..cli import config

    loaded = getattr(getattr(config.OPTIONS, "value", None), "loaded_config", None)
    if loaded is not None:
        path, profile = loaded
    else:
        path = os.environ.get(CONFIG_FILE_ENV) or None
        profile = os.environ.get(PROFILE_ENV)

    # load_config inserts the path into the reader's class-level lists, so
    # read through a subclass with copies to leave the CLI's reader as it was.
    reader = type(
        "ProbeConfigReader",
        (config.ConfigReader,),
        {
            "config_files": list(config.ConfigReader.config_files),
            "config_searchpath": list(config.ConfigReader.config_searchpath),
        },
    )
    probe = config.Options()
    reader.load_config(probe, path=path, profile=profile)
    return probe


def _options_value(opts, keys, parse):
    """The first of ``keys`` that ``parse`` recognises in ``opts``, and the key."""
    for key in keys:
        value = parse(getattr(opts, key, None))
        if value is not None:
            return value, f"{key} in config.ini"
    return None, None


def _config_value(keys, parse, off, read_config):
    """What config.ini sets for ``keys``, and the key that set it.

    Checked two ways, and either one saying ``off`` wins:

    * the options the command loaded, which honour ``--config-file`` and
      ``--profile`` - but only exist if the command loads config at all;
    * a fresh read of config.ini by ``read_config``, with the same file and
      profile, which a caller can pass to share one read with its own
      config.ini checks.

    Otherwise the loaded options win. Fails closed: if the config cannot be
    read we cannot confirm the user has not turned it off, so it is ``off``,
    from :data:`CONFIG_UNREADABLE`. ``(None, None)`` when config.ini does not
    decide.
    """
    from ..cli import config

    loaded = (None, None)
    opts = getattr(config.OPTIONS, "value", None)
    if opts is not None:
        loaded = _options_value(opts, keys, parse)
        if loaded[0] == off:
            return loaded
    try:
        fresh = _options_value(read_config(), keys, parse)
    except Exception:  # pylint: disable=broad-exception-caught
        return off, CONFIG_UNREADABLE
    if fresh[0] == off or loaded[0] is None:
        return fresh
    return loaded


def config_mode(
    kind: Kind, read_config=read_config_file
) -> tuple[Mode | None, str | None]:
    """The mode config.ini sets for ``kind``, and the key that set it.

    The key for ``kind`` (``telemetry_usage_reporting`` or
    ``telemetry_error_reporting``) wins over ``telemetry``; an unrecognised
    value is ignored. A ``disabled`` in either read wins, and an unreadable
    file is disabled (see :func:`_config_value`).
    """
    return _config_value(
        (_KIND_CONFIG_KEY[kind], CONFIG_KEY), parse_mode, Mode.DISABLED, read_config
    )


def _parse_switch_value(value):
    return parse_switch(value) if isinstance(value, str) else None


def install_id_mode(
    env: "os._Environ[str] | dict[str, str] | None" = None,
    read_config=read_config_file,
) -> tuple[bool, str]:
    """Whether usage telemetry may store an install ID, and what decided.

    ``CLOUDSMITH_TELEMETRY_INSTALL_ID`` wins over ``telemetry_install_id`` in
    config.ini; both take on/off values, and an unrecognised one is ignored.
    On by default. An unreadable config.ini turns it off: storing nothing is
    the safe side.
    """
    enabled = parse_switch(_env_value(env, INSTALL_ID_ENV))
    if enabled is not None:
        return enabled, INSTALL_ID_ENV
    enabled, source = _config_value(
        (INSTALL_ID_CONFIG_KEY,), _parse_switch_value, False, read_config
    )
    if enabled is None:
        return True, "default"
    return enabled, source


def resolve_mode(kind: Kind, read_config=read_config_file) -> tuple[Mode, str]:
    """The mode of ``kind`` of telemetry for this run, and what set it.

    The environment variables (see :func:`env_mode`) win over config.ini
    (see :func:`config_mode`), which is only read when none of them decides.
    The source is a variable name, a config.ini key, or ``default``.
    """
    mode, source = env_mode(kind)
    if mode is None:
        mode, source = config_mode(kind, read_config)
    if mode is None:
        return Mode.ENABLED, "default"
    return mode, source


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


def is_cloudsmith_host(url_or_host):
    """Tell whether ``url_or_host`` is a Cloudsmith host (empty means default)."""
    if not url_or_host:
        return True
    text = url_or_host.strip()
    host = urlsplit(text if "://" in text else f"//{text}").hostname or ""
    host = host.lower().rstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in CLOUDSMITH_HOST_SUFFIXES
    )


class WaitBudget:
    """One wait budget per process for background work at command exit.

    The update check and usage telemetry both wait for a background thread
    when the command ends; together they must not exceed ``total`` seconds.
    """

    _shared = None

    def __init__(self, total=1.0):
        self._remaining = total

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def remaining(self):
        return max(0.0, self._remaining)

    def spend(self, seconds):
        self._remaining = max(0.0, self._remaining - max(0.0, seconds))

    def reset(self, total=1.0):
        self._remaining = total
