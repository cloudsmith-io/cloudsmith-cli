# Copyright 2026 Cloudsmith Ltd
"""The usage telemetry state file, ``telemetry.json`` in the config dir.

Holds the install ID (only when enabled), the shown notice version and the
time of the last failed send. Read and written on the main thread only.

Every read-modify-write holds an inter-process lock (``locked``), so two
CLI processes cannot overwrite each other's changes, e.g. put back an
install ID that ``telemetry reset`` just deleted.
"""

import contextlib
import json
import os
import sys
import time

STATE_FILE_NAME = "telemetry.json"
LOCK_FILE_NAME = "telemetry.json.lock"
#: Writers hold the lock for one small read and write. If it is still held
#: after this, give up rather than delay the command.
LOCK_TIMEOUT_SECONDS = 0.5
_LOCK = {"depth": 0}


def config_dir():
    from ...cli.config import get_default_config_path

    return get_default_config_path()


def state_path():
    return os.path.join(config_dir(), STATE_FILE_NAME)


def writable():
    """Tell whether the state file could be written, without creating anything.

    Walks up from the config dir to the nearest directory that exists, since
    ``write`` creates the missing levels.
    """
    try:
        path = os.path.abspath(config_dir())
        while not os.path.isdir(path):
            parent = os.path.dirname(path)
            if parent == path:
                return False
            path = parent
        return os.access(path, os.W_OK)
    except OSError:
        return False


def read():
    try:
        with open(state_path(), encoding="utf-8") as state_file:
            data = json.load(state_file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _try_lock(handle):
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _acquire():
    """Open and lock the lock file; None if that fails or times out."""
    try:
        os.makedirs(config_dir(), mode=0o700, exist_ok=True)
        handle = open(  # noqa: SIM115 - closed by _unlock
            os.path.join(config_dir(), LOCK_FILE_NAME), "a+", encoding="utf-8"
        )
    except OSError:
        return None
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            _try_lock(handle)
            return handle
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                return None
            time.sleep(0.01)


@contextlib.contextmanager
def locked():
    """Hold the state lock; yields False if it could not be taken.

    Re-entrant within the process, so a caller can hold it across a whole
    read-check-write that itself calls ``write`` or ``delete``.
    """
    if _LOCK["depth"]:
        _LOCK["depth"] += 1
        try:
            yield True
        finally:
            _LOCK["depth"] -= 1
        return
    handle = _acquire()
    if handle is None:
        yield False
        return
    _LOCK["depth"] = 1
    try:
        yield True
    finally:
        _LOCK["depth"] = 0
        _unlock(handle)


def write(updates):
    from ..cache_utils import atomic_write_json

    with locked() as ok:
        if not ok:
            return False
        data = read()
        data.update(updates)
        try:
            atomic_write_json(state_path(), data)
        except OSError:
            return False
    return True


def delete():
    with locked() as ok:
        if not ok:
            return False
        try:
            os.remove(state_path())
        except FileNotFoundError:
            return True
        except OSError:
            return False
    return True
