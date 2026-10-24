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


# A batch file expands % even inside quotes and cannot hold " or a line break.
_UNSAFE_IN_BATCH = ('"', "%", "\r", "\n")


class UnsafeLauncherValue(ValueError):
    """Raised when a value cannot go into a launcher script."""


def batch_value(name: str, value: str) -> str:
    """Return *value* in a form that a batch file holds without change.

    ``cmd.exe`` reads a batch file in the console code page, so the file must
    be ASCII.  A path under the user profile is written as ``%USERPROFILE%``,
    which ``cmd.exe`` expands to the correct Unicode path when it runs.  An
    ASCII path stays literal, because another account that runs the package
    manager has a different profile.
    """
    if any(char in value for char in _UNSAFE_IN_BATCH):
        raise UnsafeLauncherValue(
            f"{name} {value!r} cannot go into the launcher: a batch file cannot "
            "hold a '\"', a '%' or a line break."
        )
    profile = os.environ.get("USERPROFILE", "")
    lowered = value.lower()
    if (
        not value.isascii()
        and profile
        and (lowered == profile.lower() or lowered.startswith(profile.lower() + "\\"))
    ):
        value = "%USERPROFILE%" + value[len(profile) :]
    if not value.isascii():
        raise UnsafeLauncherValue(
            f"{name} {value!r} cannot go into the launcher: outside the user "
            "profile, a batch file can only hold ASCII characters. Set it in "
            "the environment that runs the package manager instead."
        )
    return value


def launcher_arg(name: str, value: str) -> str:
    """Return *value* quoted as one argument of a launcher command."""
    if is_windows():
        return f'"{batch_value(name, value)}"'
    return shlex.quote(value)


def helper_command(helper: str) -> str:
    """Return the command that a launcher runs for *helper*.

    A frozen standalone binary is not guaranteed to be on ``PATH`` as
    ``cloudsmith``, so the launcher runs the absolute executable.
    """
    if getattr(sys, "frozen", False):
        executable = launcher_arg("cloudsmith", sys.executable)
        return f"{executable} credential-helper {helper}"
    return f"cloudsmith credential-helper {helper}"


def _launcher_content(
    target_cmd: str, *, windows: bool, env: dict[str, str] | None = None
) -> str:
    """Return the launcher script body for the platform.

    Windows uses a ``.cmd`` batch file (``@echo off`` keeps stdout clean for
    Docker's credential JSON); Unix uses a ``#!/bin/sh`` script that ``exec``s
    the target so signals and the exit code pass straight through.  The
    ``env`` variables replace the caller's values, so the helper gives the
    same result as the install.
    """
    env = env or {}
    for name, value in env.items():
        if not isinstance(value, str):
            raise TypeError(
                f"{name} {value!r} cannot go into the launcher: the value must "
                f"be a string, not {type(value).__name__}."
            )
    if windows:
        settings = "".join(
            f'set "{name}={batch_value(name, value)}"\r\n'
            for name, value in env.items()
        )
        if settings:
            # Keep "!" literal and the settings local to the launcher.
            settings = f"setlocal DisableDelayedExpansion\r\n{settings}"
        return f"@echo off\r\n{settings}{target_cmd} %*\r\n"
    settings = "".join(
        f"export {name}={shlex.quote(value)}\n" for name, value in env.items()
    )
    return f'#!/bin/sh\n{settings}exec {target_cmd} "$@"\n'


def write_launcher(
    bin_dir: Path,
    name: str,
    target_cmd: str,
    dry_run=False,
    env: dict[str, str] | None = None,
) -> Path:
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
    env:
        Environment variables that the launcher sets.

    Returns
    -------
    Path
        The path of the written file.
    """
    windows = is_windows()
    content = _launcher_content(target_cmd, windows=windows, env=env)
    if dry_run:
        if windows:
            return bin_dir / f"{name}.cmd"
        else:
            return bin_dir / name
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)

    dest = bin_dir / _launcher_filename(name, windows=windows)
    dest.write_text(content, encoding="utf-8", newline="")
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
