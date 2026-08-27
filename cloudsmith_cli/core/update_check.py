"""Check for new CLI versions against Cloudsmith-hosted release manifests."""

import json
import logging
import os
import sys
import threading
import time

import click

from ..cli.config import get_default_config_path
from . import version

logger = logging.getLogger(__name__)

MANIFEST_URL_TEMPLATE = (
    "https://dl.cloudsmith.io/public/cloudsmith/cli/raw/names/"
    "cloudsmith-cli-manifest-{target}/versions/latest/manifest.txt"
)
VERSION_PROBE_TARGET = "linux-x86_64-gnu"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
BACKGROUND_JOIN_TIMEOUT_SECONDS = 1.0
CACHE_FILE_NAME = "update_check.json"
MACHINE_OUTPUT_FORMATS = ("json", "pretty_json")
SUPPRESSED_SUBCOMMANDS = frozenset(("mcp", "upgrade"))


def parse_manifest(text):
    """Parse the key=value lines of a release manifest into a dict."""
    manifest = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        manifest[key.strip()] = value.strip()
    return manifest


def fetch_latest_manifest(target=None, timeout=5.0):
    """Fetch and parse the latest release manifest for a build target."""
    from .session import create_requests_session

    url = MANIFEST_URL_TEMPLATE.format(target=target or VERSION_PROBE_TARGET)
    response = create_requests_session().get(url, timeout=timeout)
    response.raise_for_status()
    manifest = parse_manifest(response.text)
    if "version" not in manifest:
        raise ValueError(f"no version field in manifest from {url}")
    return manifest


def get_cache_file_path():
    """Return the path of the update check cache file."""
    return os.path.join(get_default_config_path(), CACHE_FILE_NAME)


def read_cached_state():
    """Read the cached update check state, or an empty dict."""
    try:
        with open(get_cache_file_path(), encoding="utf-8") as cache_file:
            state = json.load(cache_file)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_cached_state(latest_version):
    """Write the cached update check state atomically."""
    from .cache_utils import atomic_write_json

    path = get_cache_file_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    state = {"checked_at": time.time(), "latest_version": latest_version}
    atomic_write_json(path, state)


def store_latest_version(latest_version):
    """Write the cached update check state; ignore storage errors."""
    try:
        write_cached_state(latest_version)
    except OSError:
        logger.debug("Failed to store the update check state", exc_info=True)


def cache_is_fresh(state, now=None, interval=DEFAULT_INTERVAL_SECONDS):
    """Tell whether the cached state is younger than the check interval."""
    try:
        checked_at = float(state["checked_at"])
    except (KeyError, TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    return (now - checked_at) < interval


def stderr_is_tty():
    """Tell whether stderr is attached to a terminal."""
    return sys.stderr is not None and sys.stderr.isatty()


def update_check_enabled(opts, invoked_subcommand):
    """Tell whether the update check runs for this invocation."""
    env_value = os.environ.get("CLOUDSMITH_NO_UPDATE_CHECK", "").strip().lower()
    if env_value in ("1", "true", "yes"):
        return False
    if os.environ.get("CI"):
        return False
    if not stderr_is_tty():
        return False
    if opts.output in MACHINE_OUTPUT_FORMATS:
        return False
    return invoked_subcommand not in SUPPRESSED_SUBCOMMANDS


def get_available_update():
    """Return the cached latest version if it is newer, else None."""
    latest = read_cached_state().get("latest_version")
    if not latest:
        return None
    try:
        newer = version.parse_version(latest) > version.get_version_info()
    except (TypeError, ValueError):
        return None
    return latest if newer else None


def start_background_check_if_stale():
    """Refresh the cached latest version in a daemon thread if stale."""
    state = read_cached_state()
    if cache_is_fresh(state):
        return None
    try:
        write_cached_state(state.get("latest_version"))
    except OSError:
        logger.debug("Cannot write the update check state", exc_info=True)
        return None

    def refresh():
        try:
            from . import installation

            manifest = fetch_latest_manifest(target=installation.detect_target())
            write_cached_state(manifest["version"])
        except (OSError, ValueError):
            logger.debug("Update check failed", exc_info=True)

    thread = threading.Thread(
        target=refresh, name="cloudsmith-update-check", daemon=True
    )
    thread.start()
    return thread


def print_update_notice_if_available():
    """Print an update notice on stderr when a newer version is cached."""
    latest = get_available_update()
    if latest is None:
        return
    current = version.get_version()
    click.secho(
        f"\nA new version of the Cloudsmith CLI is available: {current} → {latest}",
        fg="yellow",
        err=True,
    )
    click.secho("Run `cloudsmith upgrade` to get it.", fg="yellow", err=True)


def arm(ctx, opts):
    """Start the update check and register the exit notice, if enabled."""
    invoked = ctx.invoked_subcommand
    invoked = getattr(ctx.command, "inverse", {}).get(invoked, invoked)
    if not update_check_enabled(opts, invoked):
        return
    thread = start_background_check_if_stale()
    ctx.call_on_close(lambda: _finish_and_print_notice(opts, thread))


def _finish_and_print_notice(opts, thread):
    if opts.output in MACHINE_OUTPUT_FORMATS:
        return
    try:
        if thread is not None:
            thread.join(BACKGROUND_JOIN_TIMEOUT_SECONDS)
        print_update_notice_if_available()
    except OSError:
        logger.debug("Update notice failed", exc_info=True)
