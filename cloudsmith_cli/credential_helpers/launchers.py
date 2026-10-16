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
import shlex
import shutil
import sys
from pathlib import Path


def is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


def launcher_filename(name: str, *, windows: bool, windows_suffix: str = ".cmd") -> str:
    """Return the launcher file name for the platform (``.cmd`` on Windows)."""
    return f"{name}{windows_suffix}" if windows else name


# Settings with no CLI flag that change where a helper finds credentials.
ENV_ONLY_SETTINGS = (
    "CLOUDSMITH_NO_KEYRING",
    "CLOUDSMITH_KEYRING_BACKEND",
    "CLOUDSMITH_KEYRING_FILE_PATH",
    "CLOUDSMITH_KEYRING_DIR",
)
_PATH_SETTINGS = ("CLOUDSMITH_KEYRING_FILE_PATH", "CLOUDSMITH_KEYRING_DIR")

# A batch file expands % even inside quotes and cannot hold " or a line break.
_UNSAFE_IN_BATCH = ('"', "%", "\r", "\n")


class UnsafeLauncherValue(ValueError):
    """Raised when a value cannot go into a launcher script."""


def install_time_settings(supplied: dict[str, str | None]) -> dict[str, str]:
    """Return the ``CLOUDSMITH_*`` settings that a launcher keeps.

    A package manager can run its helper from an IDE or a build agent that
    does not have the environment of the install.  *supplied* holds the
    settings that the install got from a flag or an environment variable.
    Paths are made absolute, because the helper runs in another directory.
    """
    settings = dict(supplied)
    for name in _PATH_SETTINGS:
        path = settings.get(name)
        if path:
            settings[name] = os.path.abspath(
                os.path.expanduser(os.path.expandvars(path))
            )
    return {name: value for name, value in settings.items() if value}


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


def write_launcher(
    bin_dir: Path,
    name: str,
    target_cmd: str,
    dry_run=False,
    windows_suffix=".cmd",
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
    windows_suffix:
        The launcher file extension on Windows. NuGet discovers only ``.bat``.
    env:
        Environment variables that the launcher sets.

    Returns
    -------
    Path
        The path of the written file.
    """
    windows = is_windows()
    filename = launcher_filename(name, windows=windows, windows_suffix=windows_suffix)
    content = _launcher_content(target_cmd, windows=windows, env=env)
    if dry_run:
        return bin_dir / filename
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)

    dest = bin_dir / filename
    dest.write_text(content, encoding="utf-8", newline="")
    if not windows:
        dest.chmod(0o755)

    return dest


def remove_launcher(
    bin_dir: Path, name: str, dry_run=False, windows_suffix=".cmd"
) -> bool:
    """Remove a launcher previously created by :func:`write_launcher`.

    Parameters
    ----------
    bin_dir:
        Directory that contains (or contained) the launcher.
    name:
        Base name of the helper binary (without extension).
    windows_suffix:
        The launcher file extension on Windows.

    Returns
    -------
    bool
        ``True`` if a file was removed, ``False`` if no file was found.
    """
    target = Path(bin_dir) / launcher_filename(
        name, windows=is_windows(), windows_suffix=windows_suffix
    )

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
    2. The directory of the running ``cloudsmith`` executable — if that
        directory is writable.
    3. The user-local bin directory (see :func:`_user_bin_dir`).

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

    # Option 2: beside the running cloudsmith binary (if writable)
    cloudsmith_path = shutil.which("cloudsmith")
    if cloudsmith_path:
        candidate = Path(os.path.dirname(os.path.realpath(cloudsmith_path)))
    else:
        candidate = Path(os.path.dirname(os.path.realpath(sys.argv[0])))

    if os.access(candidate, os.W_OK | os.X_OK):
        return candidate.resolve()

    # Option 3: user-local bin
    return _user_bin_dir(is_windows()).resolve()


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
