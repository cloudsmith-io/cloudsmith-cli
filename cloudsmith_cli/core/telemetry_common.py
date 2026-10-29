# Copyright 2026 Cloudsmith Ltd
"""Helpers shared by error reporting, update checks and usage telemetry.

Keep this module's imports light (no ``requests``, ``ssl`` or ``urllib3``):
it is imported on every command.
"""

import os
import sys
from urllib.parse import urlsplit

NO_TELEMETRY_ENV = "CLOUDSMITH_NO_TELEMETRY"
DO_NOT_TRACK_ENV = "DO_NOT_TRACK"
OPT_OUT_ENVS = (DO_NOT_TRACK_ENV, NO_TELEMETRY_ENV)
_TRUTHY_ENV_VALUES = ("1", "true", "yes")

PROFILE_ENV = "CLOUDSMITH_PROFILE"
CONFIG_FILE_ENV = "CLOUDSMITH_CONFIG_FILE"

#: Hosts whose API traffic may be measured; any other host (self-hosted,
#: proxies, internal registries) never sends usage telemetry.
CLOUDSMITH_HOST_SUFFIXES = ("cloudsmith.io", "cloudsmith.com")


def telemetry_disabled(env: "os._Environ[str] | dict[str, str] | None" = None) -> bool:
    """Tell whether the user has opted out of telemetry (error reporting and usage).

    Either opt-out variable set to ``1``/``true``/``yes`` (case-insensitive)
    disables both. Any other value, or unset, leaves them on.
    """
    env = os.environ if env is None else env
    return any(
        env.get(name, "").strip().lower() in _TRUTHY_ENV_VALUES for name in OPT_OUT_ENVS
    )


def read_config_file():
    """Read config.ini afresh (``[default]`` plus ``$CLOUDSMITH_PROFILE``).

    The file named by ``$CLOUDSMITH_CONFIG_FILE`` is read first, as the CLI
    reads it. Returns new options holding what the files set. Covers commands
    that never load config or failed before doing so. Raises if a file cannot
    be read; callers fail closed.
    """
    from ..cli import config

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
    reader.load_config(
        probe,
        path=os.environ.get(CONFIG_FILE_ENV) or None,
        profile=os.environ.get(PROFILE_ENV),
    )
    return probe


def config_disabled(read_config=read_config_file) -> bool:
    """Tell whether ``telemetry = false`` is set in config.ini.

    It turns off telemetry (error reporting and usage).

    Checked two ways, and either one saying ``false`` wins:

    * the options the command loaded, which honour ``--config-file`` and
      ``--profile`` - but only exist if the command loads config at all;
    * a fresh read of config.ini by ``read_config``, which a caller can pass
      to share one read with its own config.ini checks.

    Fails closed: if the config cannot be read we cannot confirm the user has
    not opted out, so we send nothing.
    """
    try:
        from ..cli import config

        opts = getattr(config.OPTIONS, "value", None)
        if opts is not None and opts.telemetry is False:
            return True

        return read_config().telemetry is False
    except Exception:  # pylint: disable=broad-exception-caught
        return True


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
