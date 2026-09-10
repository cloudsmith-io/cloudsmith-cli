"""Decide when to check for a newer CLI version, and record what we found.

This module answers *whether* an update check (a network fetch) should run now
and stores *when* the last successful check happened together with the latest
version it reported. It performs no network access itself and renders no
notice; those belong to the actual update-check implementation that calls into
here.

The decision to act (fetch and/or notify) combines, in precedence order:

1. The ``--no-check-update`` flag.
2. The ``CLOUDSMITH_NO_UPDATE_CHECK`` environment variable (and ``CI``).
3. The ``check_for_update`` config-file key.
4. A once-every-24-hours freshness rule backed by an on-disk timestamp.

A single ``last_check_at`` timestamp throttles both the network fetch and the
"an update is available" notice to at most once a day. When the caller acts —
whether it fetches a new version or merely reprints the notice for a version it
already knows is newer — it bumps ``last_check_at`` so nothing repeats until the
day is up. Deciding whether a notice is warranted (as opposed to whether it is
*time* to act) is left to :func:`should_notify`.
"""

import json
import logging
import os
import sys
import threading
import time

from ..cli.config import get_default_config_path
from . import version

logger = logging.getLogger(__name__)

CACHE_FILE_NAME = "update_check.json"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
NO_UPDATE_CHECK_ENV = "CLOUDSMITH_NO_UPDATE_CHECK"
_TRUTHY_ENV_VALUES = ("1", "true", "yes")

#: The manifest the release workflow publishes per build target. We only read
#: ``version`` from it, so any existing target works as a probe; the download
#: fields (``url``/``sha256``) belong to the self-update path.
MANIFEST_URL_TEMPLATE = (
    "https://dl.cloudsmith.io/public/cloudsmith/cli/raw/names/"
    "cloudsmith-cli-manifest-{target}/versions/latest/manifest.txt"
)
VERSION_PROBE_TARGET = "linux-x86_64-gnu"
MANIFEST_FETCH_TIMEOUT_SECONDS = 5.0
#: How long the command waits at exit for the background fetch to finish.
BACKGROUND_JOIN_TIMEOUT_SECONDS = 1.0

#: Output formats that suppress the interactive update notice.
MACHINE_OUTPUT_FORMATS = ("json", "pretty_json")
#: Subcommands that suppress the interactive update notice.
NOTICE_SUPPRESSED_SUBCOMMANDS = frozenset(("mcp", "update", "upgrade"))


def get_state_file_path():
    """Return the path of the update-check state file."""
    return os.path.join(get_default_config_path(), CACHE_FILE_NAME)


def read_cached_state():
    """Return the cached update-check state as a dict, or an empty dict.

    Tolerant of a missing, unreadable, corrupt, or unexpectedly-shaped file:
    any such case returns ``{}``.
    """
    try:
        with open(get_state_file_path(), encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def read_last_check_time():
    """Return the unix timestamp of the last check, or None."""
    try:
        return float(read_cached_state().get("last_check_at"))
    except (TypeError, ValueError):
        return None


def read_latest_version():
    """Return the latest version reported by the last check, or None."""
    latest = read_cached_state().get("latest_version")
    return latest or None


def record_check(latest_version, now=None):
    """Record a successful check's timestamp and reported latest version.

    Called only after a successful check. A failure to persist the state must
    never break the running command, so storage errors are swallowed.
    """
    from .cache_utils import atomic_write_json

    now = time.time() if now is None else now
    path = get_state_file_path()
    state = {"last_check_at": now, "latest_version": latest_version}
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        atomic_write_json(path, state)
    except OSError:
        logger.debug("Failed to record the update-check state", exc_info=True)


def parse_manifest(text):
    """Parse the ``key=value`` lines of a release manifest into a dict.

    Blank lines and ``#`` comments are skipped. Unknown keys (including
    ``schema``) are kept but otherwise ignored by callers.
    """
    manifest = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        manifest[key.strip()] = value.strip()
    return manifest


def fetch_latest_manifest(
    session, target=VERSION_PROBE_TARGET, timeout=MANIFEST_FETCH_TIMEOUT_SECONDS
):
    """Fetch and parse the latest release manifest for a build target.

    ``session`` is the shared requests session (so proxy/CA/user-agent settings
    apply and redirects are followed). Raises ``requests.RequestException`` on
    network failure and ``ValueError`` if the manifest has no ``version``.
    """
    url = MANIFEST_URL_TEMPLATE.format(target=target)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    manifest = parse_manifest(response.text)
    if "version" not in manifest:
        raise ValueError(f"no version field in manifest from {url}")
    return manifest


def run_background_check(session, now=None):
    """Fetch the latest version and record it; swallow all errors.

    Intended to run in a daemon thread. Any network, parse or storage failure
    is logged at debug level and otherwise ignored so it can never disturb the
    command that spawned it.
    """
    import requests

    try:
        manifest = fetch_latest_manifest(session)
    except (requests.RequestException, ValueError):
        logger.debug("Update check fetch failed", exc_info=True)
        return
    record_check(manifest["version"], now=now)


def is_check_due(last_check_at, *, now=None, interval=DEFAULT_INTERVAL_SECONDS):
    """Tell whether at least ``interval`` seconds have elapsed since last check.

    A missing or invalid ``last_check_at`` means a check is due.
    """
    try:
        last = float(last_check_at)
    except (TypeError, ValueError):
        return True
    now = time.time() if now is None else now
    return (now - last) >= interval


def newer_version_known(latest_version, current_version=None):
    """Tell whether a cached ``latest_version`` is newer than the current one.

    Used to skip a redundant network fetch: if we already know we are behind,
    another fetch tells us nothing new. An absent or unparsable version is
    treated as "not known to be newer".
    """
    if not latest_version:
        return False
    try:
        current = (
            version.get_version_info()
            if current_version is None
            else version.parse_version(current_version)
        )
        return version.parse_version(latest_version) > current
    except (TypeError, ValueError):
        return False


def update_check_disabled(*, no_check_flag, config_value=None, env=None):
    """Tell whether the update check is disabled for this invocation.

    Precedence: ``--no-check-update`` flag, then the
    ``CLOUDSMITH_NO_UPDATE_CHECK`` env var (and ``CI``), then the
    ``check_for_update`` config key.
    """
    if no_check_flag:
        return True
    env = os.environ if env is None else env
    env_value = env.get(NO_UPDATE_CHECK_ENV, "").strip().lower()
    if env_value in _TRUTHY_ENV_VALUES:
        return True
    if env.get("CI"):
        return True
    return config_value is False


def should_check_for_update(*, no_check_flag, config_value=None, env=None, now=None):
    """Tell whether the CLI should act (fetch and/or notify) this invocation.

    True when the check is not disabled and at least a day has elapsed since
    the last action. It does not distinguish between "fetch" and "notify"; the
    caller inspects the cached state (via :func:`should_notify`) to decide which
    to do. Being behind does *not* short-circuit here — the daily notice depends
    on this returning True while a newer version is known.
    """
    if update_check_disabled(
        no_check_flag=no_check_flag, config_value=config_value, env=env
    ):
        return False
    return is_check_due(read_cached_state().get("last_check_at"), now=now)


def should_notify(state=None, *, current_version=None):
    """Tell whether an "update available" notice is warranted from cached state.

    True when the cached ``latest_version`` is newer than the running CLI. The
    once-a-day throttle is supplied separately by
    :func:`should_check_for_update`; this only judges whether there is something
    worth saying.
    """
    if state is None:
        state = read_cached_state()
    return newer_version_known(state.get("latest_version"), current_version)


def stderr_is_tty():
    """Tell whether stderr is attached to a terminal."""
    return sys.stderr is not None and sys.stderr.isatty()


def notice_suppressed(output_format=None, invoked_subcommand=None):
    """Tell whether the interactive update notice must stay silent.

    Independent of the disable controls in :func:`update_check_disabled`: this
    covers presentation reasons — machine output, a non-interactive terminal,
    or a subcommand that must never be interrupted by the notice.
    """
    if output_format in MACHINE_OUTPUT_FORMATS:
        return True
    if not stderr_is_tty():
        return True
    return invoked_subcommand in NOTICE_SUPPRESSED_SUBCOMMANDS


def print_update_notice(latest_version):
    """Print the "an update is available" notice on stderr."""
    import click

    click.secho(
        "A new version of the Cloudsmith CLI is available: "
        f"{version.get_version()} \u2192 {latest_version}. "
        "Run `cloudsmith update` to update.",
        fg="yellow",
        err=True,
    )


def _start_background_check(session):
    """Start the manifest fetch in a daemon thread and return it."""
    thread = threading.Thread(
        target=run_background_check,
        args=(session,),
        name="cloudsmith-update-check",
        daemon=True,
    )
    thread.start()
    return thread


def _finish_and_notify(thread, *, now=None):
    """Join the background fetch (bounded) then notify once a day if behind.

    Runs at command close. If a newer version is known — whether the just-joined
    fetch discovered it or the cache already held it — print the notice and bump
    ``last_check_at`` so it does not repeat until tomorrow.
    """
    if thread is not None:
        thread.join(BACKGROUND_JOIN_TIMEOUT_SECONDS)
    state = read_cached_state()
    if not should_notify(state):
        return
    print_update_notice(state["latest_version"])
    record_check(state["latest_version"], now=now)


def arm(ctx, opts, no_check_flag):
    """Wire up the update check for this invocation, if enabled.

    When a check is due and not disabled, start the background fetch (unless we
    already know we are behind, in which case there is nothing to fetch) and
    register a close handler that joins it and prints the notice. The notice is
    additionally suppressed for machine output, non-TTY stderr and certain
    subcommands via :func:`notice_suppressed`.
    """
    invoked = ctx.invoked_subcommand
    invoked = getattr(ctx.command, "inverse", {}).get(invoked, invoked)
    if notice_suppressed(getattr(opts, "output", None), invoked):
        return
    if not should_check_for_update(
        no_check_flag=no_check_flag, config_value=opts.check_for_update
    ):
        return

    thread = None
    if not should_notify():
        from .session import create_requests_session

        session = create_requests_session(user_agent=opts.api_user_agent)
        thread = _start_background_check(session)

    ctx.call_on_close(lambda: _finish_and_notify(thread))
