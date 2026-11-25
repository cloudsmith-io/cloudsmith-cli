# Copyright 2026 Cloudsmith Ltd
"""Decide when to check for a newer CLI version, and when to notify about it.

State lives in a small JSON file for each major version, with two timestamps,
the last-seen version and a higher major version, if one exists:
``{last_checked_at, last_notified_at, latest_version, new_major_version}``.

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
from typing import TYPE_CHECKING, Any

from ..cli.config import get_default_config_path
from . import version

if TYPE_CHECKING:
    import click
    import requests

    from ..cli.config import Options

logger = logging.getLogger(__name__)

CACHE_FILE_NAME = "update_check-v{major}.json"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
NO_UPDATE_CHECK_ENV = "CLOUDSMITH_NO_UPDATE_CHECK"
_TRUTHY_ENV_VALUES = ("1", "true", "yes")

#: The manifest the release workflow publishes per build target. We only read
#: ``version`` from it; the host's own target is probed (see ``_probe_target``)
#: so each platform tracks its own release line, and the download fields
#: (``url``/``sha256``) belong to the self-update path. Hard-coded to the
#: Cloudsmith host on purpose: this is an unattended background request made
#: before the endpoint guards run, so it must never be redirectable via env/config
#: to an untrusted host.
MANIFEST_URL_TEMPLATE = (
    "https://dl.cloudsmith.io/public/cloudsmith/cli/raw/names/"
    "{name}-{target}/versions/latest/manifest.txt"
)
#: Fallback build target for the version probe when the host platform is not a
#: recognised standalone target (e.g. pip/pipx installs). Any published target
#: works as a probe since we only read ``version``; the host's own target is
#: preferred so per-platform release skew never yields a wrong "latest".
VERSION_PROBE_TARGET = "linux-x86_64-gnu"
MANIFEST_FETCH_TIMEOUT_SECONDS = 5.0
#: How long the command waits at exit for the background fetch to finish.
BACKGROUND_JOIN_TIMEOUT_SECONDS = 1.0
_META_KEY = "cloudsmith_update_check"

#: Output formats that suppress the interactive update notice.
MACHINE_OUTPUT_FORMATS = ("json", "pretty_json")
#: Subcommands that suppress the interactive update notice.
NOTICE_SUPPRESSED_SUBCOMMANDS = frozenset(("mcp", "update", "upgrade"))


def get_state_file_path() -> str:
    """Return the path of the update-check state file of the running major version."""
    major = version.get_version().split(".", 1)[0]
    return os.path.join(get_default_config_path(), CACHE_FILE_NAME.format(major=major))


def read_cached_state() -> dict[str, Any]:
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


def _read_timestamp(key: str) -> float | None:
    """Return a float timestamp for ``key`` from the cached state, or None."""
    try:
        return float(read_cached_state().get(key))
    except (TypeError, ValueError):
        return None


def read_last_check_time() -> float | None:
    """Return the unix timestamp of the last check, or None."""
    return _read_timestamp("last_checked_at")


def read_last_notified_time() -> float | None:
    """Return the unix timestamp of the last notice, or None."""
    return _read_timestamp("last_notified_at")


def read_latest_version() -> str | None:
    """Return the latest version reported by the last check, or None."""
    latest = read_cached_state().get("latest_version")
    return latest or None


def _write_state(updates: dict[str, Any]) -> None:
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


def record_check(
    latest_version: str,
    new_major_version: str | None = None,
    now: float | None = None,
) -> None:
    """Record a check's timestamp and reported latest version.

    Preserves ``last_notified_at``. Called after a fetch, or when a
    cache-confirmed newer version re-arms the daily check without a fetch.
    """
    now = time.time() if now is None else now
    _write_state(
        {
            "last_checked_at": now,
            "latest_version": latest_version,
            "new_major_version": new_major_version,
        }
    )


def record_notified(now: float | None = None) -> None:
    """Record that the update notice was just shown. Preserves the rest."""
    now = time.time() if now is None else now
    _write_state({"last_notified_at": now})


def record_checked_and_notified(
    latest_version: str,
    new_major_version: str | None = None,
    now: float | None = None,
) -> None:
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
            "new_major_version": new_major_version,
        }
    )


def parse_manifest(text: str) -> dict[str, str]:
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


def manifest_url(target: str, major: int | None = None) -> str:
    """Return the manifest URL of the ``latest`` channel, or of one major version."""
    name = "cloudsmith-cli-manifest"
    if major is not None:
        name = f"cloudsmith-cli-v{major}-manifest"
    return MANIFEST_URL_TEMPLATE.format(name=name, target=target)


def fetch_latest_manifest(
    session: "requests.Session",
    target: str = VERSION_PROBE_TARGET,
    timeout: float = MANIFEST_FETCH_TIMEOUT_SECONDS,
    major: int | None = None,
) -> dict[str, str]:
    """Fetch and parse the latest release manifest for a build target.

    ``session`` is the shared requests session (so proxy/CA/user-agent settings
    apply and redirects are followed). Raises ``requests.RequestException`` on
    network failure and ``ValueError`` if the manifest has no ``version``.
    With ``major``, the manifest is the highest release of that major version.
    """
    url = manifest_url(target, major)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    manifest = parse_manifest(response.text)
    if "version" not in manifest:
        raise ValueError(f"no version field in manifest from {url}")
    return manifest


def _probe_target() -> str:
    """Return the build target to probe for the latest version.

    Prefers the host platform's own standalone target so each platform checks
    its own release line (per-platform release skew never yields a wrong
    "latest"); falls back to :data:`VERSION_PROBE_TARGET` when the host is not a
    recognised standalone target.
    """
    from . import installation

    return installation.detect_target() or VERSION_PROBE_TARGET


def is_higher_major(candidate: str | None, current_version: str | None = None) -> bool:
    """Tell whether ``candidate`` is in a higher major version than the current one."""
    if not candidate:
        return False
    try:
        current = (
            version.get_version_info()
            if current_version is None
            else version.parse_version(current_version)
        )
        return version.parse_version(candidate).major > current.major
    except (TypeError, ValueError):
        return False


def fetch_update_manifests(
    session: "requests.Session", target: str
) -> tuple[dict[str, str], str | None]:
    """Return the newest manifest of the running major, and a higher major version.

    The ``latest`` channel holds the highest release of all majors. When that
    release is in the running major, one fetch gives both results, and the
    higher major version is None.
    """
    newest = fetch_latest_manifest(session, target=target)
    if not is_higher_major(newest["version"]):
        return newest, None
    running_major = version.get_version_info().major
    manifest = fetch_latest_manifest(session, target=target, major=running_major)
    return manifest, newest["version"]


def run_background_check(session: "requests.Session", now: float | None = None) -> None:
    """Fetch the latest version and record it; swallow all errors.

    Intended to run in a daemon thread. Any network, parse or storage failure
    is logged at debug level and otherwise ignored so it can never disturb the
    command that spawned it.
    """
    import requests

    try:
        manifest, new_major_version = fetch_update_manifests(session, _probe_target())
    except (requests.RequestException, ValueError):
        logger.debug("Update check fetch failed", exc_info=True)
        return
    record_check(manifest["version"], new_major_version, now=now)


def is_check_due(
    last_check_at: float | str | None,
    *,
    now: float | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> bool:
    """Tell whether at least ``interval`` seconds have elapsed since last check.

    A missing or invalid ``last_check_at`` means a check is due.
    """
    if last_check_at is None:
        return True
    try:
        last = float(last_check_at)
    except (TypeError, ValueError):
        return True
    now = time.time() if now is None else now
    return (now - last) >= interval


def newer_version_known(
    latest_version: str | None, current_version: str | None = None
) -> bool:
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


def update_check_disabled(
    *,
    no_check_flag: bool,
    config_value: bool | None = None,
    env: "os._Environ[str] | dict[str, str] | None" = None,
) -> bool:
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


def should_check_for_update(
    *,
    no_check_flag: bool,
    config_value: bool | None = None,
    env: "os._Environ[str] | dict[str, str] | None" = None,
    now: float | None = None,
) -> bool:
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


def should_notify(
    state: dict[str, Any] | None = None, *, current_version: str | None = None
) -> bool:
    """Tell whether an "update available" notice is warranted from cached state.

    True when the cached ``latest_version`` is newer than the running CLI, or
    ``new_major_version`` is a higher major, *and* a check has happened since
    the last notice (``last_notified_at < last_checked_at``). The second clause
    is the daily throttle: a check re-arms the notice, and showing it stamps
    ``last_notified_at`` to disarm it until the next check.
    """
    if state is None:
        state = read_cached_state()
    if not (
        newer_version_known(state.get("latest_version"), current_version)
        or is_higher_major(state.get("new_major_version"), current_version)
    ):
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


def stderr_is_tty() -> bool:
    """Tell whether stderr is attached to a terminal."""
    return sys.stderr is not None and sys.stderr.isatty()


def notice_suppressed(
    output_format: str | None = None, invoked_subcommand: str | None = None
) -> bool:
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


def _update_action_lines() -> list[str]:
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
        return ["Replace your install with the build from the release page above."]
    return ["To update, run:", f"  {instruction}"]


def new_major_lines(new_major_version: str) -> list[str]:
    """Return the lines that suggest a new major version."""
    from . import installation

    first_release = f"{version.parse_version(new_major_version).major}.0.0"
    return [
        (
            f"Cloudsmith CLI {new_major_version} is available. "
            "It is a new major version with breaking changes."
        ),
        (
            "Read what changed before you upgrade: "
            f"{installation.changelog_url(first_release)}"
        ),
    ]


def print_update_notice(
    latest_version: str | None, new_major_version: str | None = None
) -> None:
    """Print the "an update is available" notice on stderr."""
    import click

    from . import installation

    lines = []
    if newer_version_known(latest_version):
        lines += [
            (
                "A new version of the Cloudsmith CLI is available: "
                f"{version.get_version()} -> {latest_version}."
            ),
            f"See what's changed: {installation.changelog_url(latest_version)}",
            *_update_action_lines(),
        ]
    if is_higher_major(new_major_version):
        lines += new_major_lines(new_major_version)
    click.secho("\n".join(lines), fg="yellow", err=True)


def _start_background_check(session: "requests.Session") -> threading.Thread:
    """Start the manifest fetch in a daemon thread and return it."""
    thread = threading.Thread(
        target=run_background_check,
        args=(session,),
        name="cloudsmith-update-check",
        daemon=True,
    )
    thread.start()
    return thread


def _finish_and_notify(
    thread: threading.Thread | None,
    opts: "Options",
    invoked: str | None,
    *,
    now: float | None = None,
) -> None:
    """Join the background fetch (bounded) then notify if warranted.

    Runs at command close. Presentation suppressors are evaluated here (not at
    decision time) so a subcommand's own ``-F`` and the live TTY state are
    known. When suppressed, ``last_notified_at`` is left untouched so a later
    interactive run can still speak.
    """
    if thread is not None:
        from .telemetry_common import WaitBudget

        budget = WaitBudget.shared()
        started = time.monotonic()
        thread.join(min(BACKGROUND_JOIN_TIMEOUT_SECONDS, budget.remaining()))
        budget.spend(time.monotonic() - started)
    if notice_suppressed(getattr(opts, "output", None), invoked):
        return
    state = read_cached_state()
    if not should_notify(state):
        return
    print_update_notice(state.get("latest_version"), state.get("new_major_version"))
    record_notified(now=now)


def arm(ctx: "click.Context", opts: "Options", no_check_flag: bool) -> None:
    """Wire up the update check for this invocation.

    Unless disabled (``--no-check-update``/env/``CI``/config), a close handler is
    always registered so a pending notice can fire from cache even on a run where
    no fetch is due. When a fetch *is* due, :func:`start` runs it after the
    command resolves its connection options, so the manifest keeps
    refreshing and a release newer than a previously-seen one is picked up. The
    fetch runs even when the notice is suppressed (e.g. ``-F json``, non-TTY),
    keeping the cache warm; the close handler decides separately whether to
    print. Notification throttling is independent of the fetch: it lives in
    :func:`should_notify` via ``last_notified_at < last_checked_at``, so a user
    who ignores the notice is not re-nagged until the next due check even though
    the fetch still happens.
    """
    invoked = ctx.invoked_subcommand
    invoked = getattr(ctx.command, "inverse", {}).get(invoked, invoked)
    if update_check_disabled(
        no_check_flag=no_check_flag, config_value=opts.check_for_update
    ):
        return

    check = {"due": is_check_due(read_last_check_time()), "thread": None}
    ctx.meta[_META_KEY] = check
    ctx.call_on_close(lambda: _finish_and_notify(check["thread"], opts, invoked))


def start(ctx: "click.Context", opts: "Options") -> None:
    """Start a due fetch with the connection options of the command.

    Commands that make no HTTP requests never call this, so the fetch waits
    for the next command that does.
    """
    check = ctx.meta.get(_META_KEY)
    if not check or not check["due"]:
        return
    check["due"] = False

    from .session import create_requests_session

    session = create_requests_session(
        proxy=opts.proxy,
        ssl_verify=opts.ssl_verify,
        ssl_verify_strict=opts.ssl_verify_strict,
        user_agent=opts.api_user_agent,
    )
    check["thread"] = _start_background_check(session)
