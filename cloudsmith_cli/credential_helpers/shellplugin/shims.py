# Copyright 2026 Cloudsmith Ltd
"""Shim writer for shell-plugin package managers.

A shim is a tiny launcher (reusing the credential-helper launcher body) named
after the real binary (e.g. ``mvn``) that re-execs ``cloudsmith exec -- <bin>
"$@"``.  Placed first on PATH (via ``credential-helper shell-init``), it
shadows the real binary so every invocation is wrapped with Cloudsmith
credentials; ``exec`` infers the right plugin from the binary name.
"""

from __future__ import annotations

from pathlib import Path

from ..launchers import remove_launcher, write_launcher


def shim_target_cmd(binary_name: str) -> str:
    """Return the command a shim for *binary_name* forwards to."""
    return f"cloudsmith exec -- {binary_name}"


def write_shim(shims_dir: Path, binary_name: str) -> Path:
    """Write a shim named *binary_name* that wraps it via ``cloudsmith exec``."""
    return write_launcher(shims_dir, binary_name, shim_target_cmd(binary_name))


def remove_shim(shims_dir: Path, binary_name: str) -> bool:
    """Remove a shim previously created by :func:`write_shim`."""
    return remove_launcher(shims_dir, binary_name)
