# Copyright 2026 Cloudsmith Ltd
"""Launcher writer/remover for credential-helper on-PATH binaries.

Creates a thin shell script (Unix) or .cmd batch file (Windows) named
``docker-credential-cloudsmith`` (or similar) that forwards every call to the
single ``cloudsmith`` binary already installed on the user's PATH.

The platform-specific bits (file name, script body) live in
small pure helpers parameterised on ``windows`` so they can be unit-tested
without monkeypatching ``os.name`` — faking ``os.name`` on a posix host makes
``pathlib.Path`` raise ``NotImplementedError`` on Python < 3.12.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path


def is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


def _launcher_filename(name: str, *, windows: bool) -> str:
    """Return the launcher file name for the platform (``.cmd`` on Windows)."""
    return f"{name}.cmd" if windows else name


def launcher_arg(value: str) -> str:
    """Return *value* quoted as one argument of a launcher command."""
    if is_windows():
        return f'"{value}"'
    return shlex.quote(value)


def helper_command(helper: str) -> str:
    """Return the command that a launcher runs for *helper*.

    A frozen standalone binary is not guaranteed to be on ``PATH`` as
    ``cloudsmith``, so the launcher runs the absolute executable.
    """
    if getattr(sys, "frozen", False):
        return f"{launcher_arg(sys.executable)} credential-helper {helper}"
    return f"cloudsmith credential-helper {helper}"


def _launcher_content(target_cmd: str, *, windows: bool) -> str:
    """Return the launcher script body for the platform.

    Windows uses a ``.cmd`` batch file (``@echo off`` keeps stdout clean for
    Docker's credential JSON); Unix uses a ``#!/bin/sh`` script that ``exec``s
    the target so signals and the exit code pass straight through.
    """
    if windows:
        return f"@echo off\r\n{target_cmd} %*\r\n"
    return f'#!/bin/sh\nexec {target_cmd} "$@"\n'


def write_launcher(bin_dir: Path, name: str, target_cmd: str, dry_run=False) -> Path:
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
    windows = is_windows()
    if dry_run:
        if windows:
            return bin_dir / f"{name}.cmd"
        else:
            return bin_dir / name
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)

    dest = bin_dir / _launcher_filename(name, windows=windows)
    dest.write_text(
        _launcher_content(target_cmd, windows=windows), encoding="utf-8", newline=""
    )
    if not windows:
        dest.chmod(0o755)

    return dest


def remove_launcher(bin_dir: Path, name: str, dry_run=False) -> bool:
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
    target = Path(bin_dir) / _launcher_filename(name, windows=is_windows())

    if target.exists():
        if not dry_run:
            target.unlink()
        return True
    return False


def resolve_bin_dir(override: str | None = None) -> Path:
    """Determine the best directory in which to place a launcher.

    Resolution order
    ----------------
    1. *override* → resolved to an absolute path (relative paths are resolved
       against the current working directory).
    2. ``~/.cloudsmith/bin``, which a package manager upgrade never replaces.

    The chosen directory is **not** created here; that happens when the
    launcher is written via :func:`write_launcher`.

    Parameters
    ----------
    override:
        Explicit path supplied by the caller (e.g. ``--bin-dir`` CLI option).
        Both relative and absolute paths are supported; relative paths are
        resolved against the current working directory, ensuring the returned
        path is always absolute.

    Returns
    -------
    Path
        The resolved directory as an absolute path.
    """
    if override is not None:
        return Path(override).resolve()

    return (Path.home() / ".cloudsmith" / "bin").resolve()


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
