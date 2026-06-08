# Copyright 2026 Cloudsmith Ltd
"""Launcher writer/remover for credential-helper on-PATH binaries.

Creates a thin shell script (Unix) or .cmd batch file (Windows) named
``docker-credential-cloudsmith`` (or similar) that forwards every call to the
single ``cloudsmith`` binary already installed on the user's PATH.

The platform-specific bits (file name, script body, user bin directory) live in
small pure helpers parameterised on ``windows`` so they can be unit-tested
without monkeypatching ``os.name`` — faking ``os.name`` on a posix host makes
``pathlib.Path`` raise ``NotImplementedError`` on Python < 3.12.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


def _launcher_filename(name: str, *, windows: bool) -> str:
    """Return the launcher file name for the platform (``.cmd`` on Windows)."""
    return f"{name}.cmd" if windows else name


def _launcher_content(target_cmd: str, *, windows: bool) -> str:
    """Return the launcher script body for the platform.

    Windows uses a ``.cmd`` batch file (``@echo off`` keeps stdout clean for
    Docker's credential JSON); Unix uses a ``#!/bin/sh`` script that ``exec``s
    the target so signals and the exit code pass straight through.
    """
    if windows:
        return f"@echo off\r\n{target_cmd} %*\r\n"
    return f'#!/bin/sh\nexec {target_cmd} "$@"\n'


def _user_bin_dir(windows: bool) -> Path:
    """Return the user-local bin directory for the platform.

    Unix → ``~/.local/bin``; Windows → ``%LOCALAPPDATA%\\Cloudsmith\\bin``
    (falling back to the home directory when ``LOCALAPPDATA`` is unset).
    """
    if windows:
        localappdata = os.environ.get("LOCALAPPDATA")
        base = Path(localappdata) if localappdata else Path.home()
        return base / "Cloudsmith" / "bin"
    return Path.home() / ".local" / "bin"


def write_launcher(bin_dir: Path, name: str, target_cmd: str) -> Path:
    """Write a launcher script for *name* in *bin_dir* that execs *target_cmd*.

    Parameters
    ----------
    bin_dir:
        Directory in which to create the launcher.  Created if absent.
    name:
        Base name of the helper binary (e.g. ``docker-credential-cloudsmith``).
    target_cmd:
        The command the launcher forwards to (e.g.
        ``cloudsmith credential-helper docker``).

    Returns
    -------
    Path
        The path of the written file.
    """
    windows = _is_windows()
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)

    dest = bin_dir / _launcher_filename(name, windows=windows)
    dest.write_text(_launcher_content(target_cmd, windows=windows), encoding="utf-8")
    if not windows:
        dest.chmod(0o755)

    return dest


def remove_launcher(bin_dir: Path, name: str) -> bool:
    """Remove a launcher previously created by :func:`write_launcher`.

    Parameters
    ----------
    bin_dir:
        Directory that contains (or contained) the launcher.
    name:
        Base name of the helper binary (without extension).

    Returns
    -------
    bool
        ``True`` if a file was removed, ``False`` if no file was found.
    """
    target = Path(bin_dir) / _launcher_filename(name, windows=_is_windows())

    if target.exists():
        target.unlink()
        return True
    return False


def resolve_bin_dir(override: str | None = None) -> Path:
    """Determine the best directory in which to place a launcher.

    Resolution order
    ----------------
    1. *override* → ``Path(override)``.
    2. The directory of the running ``cloudsmith`` executable — if that
       directory is writable.
    3. The user-local bin directory (see :func:`_user_bin_dir`).

    The chosen directory is **not** created here; that happens when the
    launcher is written via :func:`write_launcher`.

    Parameters
    ----------
    override:
        Explicit path supplied by the caller (e.g. ``--bin-dir`` CLI option).

    Returns
    -------
    Path
        The resolved directory.
    """
    if override is not None:
        return Path(override)

    # Option 2: beside the running cloudsmith binary (if writable)
    cloudsmith_path = shutil.which("cloudsmith")
    if cloudsmith_path:
        candidate = Path(os.path.dirname(os.path.realpath(cloudsmith_path)))
    else:
        candidate = Path(os.path.dirname(os.path.realpath(sys.argv[0])))

    if os.access(candidate, os.W_OK):
        return candidate

    # Option 3: user-local bin
    return _user_bin_dir(_is_windows())


def is_on_path(directory: Path) -> bool:
    """Return True if *directory* is an entry in the current ``$PATH``.

    Comparison is case-insensitive on Windows (``os.path.normcase``) and
    normalised via ``os.path.normpath`` on all platforms.

    Parameters
    ----------
    directory:
        The directory to check.

    Returns
    -------
    bool
        ``True`` if *directory* appears in ``$PATH``.
    """
    needle = os.path.normcase(os.path.normpath(str(directory)))
    path_env = os.environ.get("PATH", "")
    for entry in path_env.split(os.pathsep):
        if not entry:
            continue
        if os.path.normcase(os.path.normpath(entry)) == needle:
            return True
    return False
