"""Decide when to check for a newer CLI version, and when to notify about it.

State lives in a small JSON file with two timestamps and the last-seen version:
``{last_checked_at, last_notified_at, latest_version}``.

Two rhythms run off it, deliberately decoupled:

* **Fetch** (network + refresh ``latest_version``) runs at most once a day,
  gated by ``last_checked_at`` and the disable controls (``--no-check-update``,
  ``CLOUDSMITH_NO_UPDATE_CHECK``, ``CI``, ``check_for_update``). It runs even in
  contexts where the notice is silenced (``-F json``, non-TTY, ``mcp``/``update``)
  so the cache stays warm for a later interactive run.

* **Notice** ("an update is available") is gated by the invariant
  ``last_notified_at < last_checked_at`` — i.e. a check has happened since we
  last spoke — plus the presentation suppressors in :func:`notice_suppressed`.
  Tying the notice to "a check we have not reported" rather than to its own
  clock keeps the two rhythms from drifting: a fetch that could not print (JSON,
  non-TTY) advances ``last_checked_at`` without spending the notice, so the next
  interactive run still notifies promptly.
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
#: Overrides ``MANIFEST_URL_TEMPLATE`` when set. Must contain a ``{target}``
#: placeholder. For testing self-update against a local or staging endpoint.
MANIFEST_URL_TEMPLATE_ENV = "CLOUDSMITH_MANIFEST_URL_TEMPLATE"
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


def _read_timestamp(key):
    """Return a float timestamp for ``key`` from the cached state, or None."""
    try:
        return float(read_cached_state().get(key))
    except (TypeError, ValueError):
        return None


def read_last_check_time():
    """Return the unix timestamp of the last check, or None."""
    return _read_timestamp("last_checked_at")


def read_last_notified_time():
    """Return the unix timestamp of the last notice, or None."""
    return _read_timestamp("last_notified_at")


def read_latest_version():
    """Return the latest version reported by the last check, or None."""
    latest = read_cached_state().get("latest_version")
    return latest or None


def _write_state(updates):
    """Merge ``updates`` into the cached state and write it; swallow errors.

    A read-modify-write so that updating one field (e.g. the check timestamp)
    never drops a sibling (e.g. the notice timestamp). A failure to persist the
    state must never break the running command.
    """
    from .cache_utils import atomic_write_json

    path = get_state_file_path()
    state = read_cached_state()
    state.update(updates)
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        atomic_write_json(path, state)
    except OSError:
        logger.debug("Failed to record the update-check state", exc_info=True)


def record_check(latest_version, now=None):
    """Record a check's timestamp and reported latest version.

    Preserves ``last_notified_at``. Called after a fetch, or when a
    cache-confirmed newer version re-arms the daily check without a fetch.
    """
    now = time.time() if now is None else now
    _write_state({"last_checked_at": now, "latest_version": latest_version})


def record_notified(now=None):
    """Record that the update notice was just shown. Preserves the rest."""
    now = time.time() if now is None else now
    _write_state({"last_notified_at": now})


def record_checked_and_notified(latest_version, now=None):
    """Stamp both timestamps and the latest version in a single write.

    Used by the ``update`` command, which performs its own check on every run
    regardless of the cache. Advancing ``last_notified_at`` alongside
    ``last_checked_at`` disarms the background notice's daily re-nag
    (``last_notified_at < last_checked_at`` becomes false) so the user is not
    told about an update they just ran the command to handle.
    """
    now = time.time() if now is None else now
    _write_state(
        {
            "last_checked_at": now,
            "last_notified_at": now,
            "latest_version": latest_version,
        }
    )


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
    template = os.environ.get(MANIFEST_URL_TEMPLATE_ENV) or MANIFEST_URL_TEMPLATE
    url = template.format(target=target)
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
    """Tell whether a check (fetch or cache-confirmed re-arm) is due this run.

    True when the check is not disabled and at least a day has elapsed since
    ``last_checked_at``. Independent of presentation: a check may run even when
    the notice will be silenced.
    """
    if update_check_disabled(
        no_check_flag=no_check_flag, config_value=config_value, env=env
    ):
        return False
    return is_check_due(read_cached_state().get("last_checked_at"), now=now)


def should_notify(state=None, *, current_version=None):
    """Tell whether an "update available" notice is warranted from cached state.

    True when the cached ``latest_version`` is newer than the running CLI *and*
    a check has happened since the last notice (``last_notified_at <
    last_checked_at``). The second clause is the daily throttle: a check re-arms
    the notice, and showing it stamps ``last_notified_at`` to disarm it until the
    next check.
    """
    if state is None:
        state = read_cached_state()
    if not newer_version_known(state.get("latest_version"), current_version):
        return False
    try:
        last_notified = float(state.get("last_notified_at") or 0)
    except (TypeError, ValueError):
        last_notified = 0.0
    try:
        last_checked = float(state.get("last_checked_at") or 0)
    except (TypeError, ValueError):
        last_checked = 0.0
    return last_notified < last_checked


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


def _update_action_lines():
    """Return the "how to update" lines for the current install channel.

    A standalone binary can update itself, so it is pointed at
    ``cloudsmith update``. Every package-managed install cannot be updated by
    the CLI, so the notice prints that channel's own upgrade command on its own
    line — easy to copy, and not mangled by terminal line-wrapping — rather than
    sending the user to a command that would only print another command.
    """
    from . import installation

    channel = installation.detect_channel()
    instruction = installation.upgrade_instruction(channel)
    if instruction is None:
        if installation.self_update_supported():
            return ["Run `cloudsmith update` to update."]
        return [
            "Download the latest build and replace your install:",
            f"  {installation.RELEASES_LATEST_URL}",
        ]
    return ["To update, run:", f"  {instruction}"]


def print_update_notice(latest_version):
    """Print the "an update is available" notice on stderr."""
    import click

    lines = [
        (
            "A new version of the Cloudsmith CLI is available: "
            f"{version.get_version()} \u2192 {latest_version}."
        ),
        *_update_action_lines(),
    ]
    click.secho("\n".join(lines), fg="yellow", err=True)


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


def _finish_and_notify(thread, opts, invoked, *, now=None):
    """Join the background fetch (bounded) then notify if warranted.

    Runs at command close. Presentation suppressors are evaluated here (not at
    decision time) so a subcommand's own ``-F`` and the live TTY state are
    known. When suppressed, ``last_notified_at`` is left untouched so a later
    interactive run can still speak.
    """
    if thread is not None:
        thread.join(BACKGROUND_JOIN_TIMEOUT_SECONDS)
    if notice_suppressed(getattr(opts, "output", None), invoked):
        return
    state = read_cached_state()
    if not should_notify(state):
        return
    print_update_notice(state["latest_version"])
    record_notified(now=now)


def arm(ctx, opts, no_check_flag):
    """Wire up the update check for this invocation.

    Unless disabled (``--no-check-update``/env/``CI``/config), a close handler is
    always registered so a pending notice can fire from cache even on a run where
    no fetch is due. When a fetch *is* due, either start the background fetch or —
    if we already know we are behind — bump ``last_checked_at`` to re-arm the
    daily notice without a fetch. The fetch runs even when the notice is
    suppressed (e.g. ``-F json``, non-TTY), keeping the cache warm; the close
    handler decides separately whether to print.
    """
    invoked = ctx.invoked_subcommand
    invoked = getattr(ctx.command, "inverse", {}).get(invoked, invoked)
    if update_check_disabled(
        no_check_flag=no_check_flag, config_value=opts.check_for_update
    ):
        return

    thread = None
    if is_check_due(read_last_check_time()):
        if newer_version_known(read_latest_version()):
            # Already behind: no fetch needed, but bump last_checked_at so the
            # daily notice re-arms (last_notified_at < last_checked_at).
            record_check(read_latest_version())
        else:
            from .session import create_requests_session

            session = create_requests_session(user_agent=opts.api_user_agent)
            thread = _start_background_check(session)

    ctx.call_on_close(lambda: _finish_and_notify(thread, opts, invoked))
