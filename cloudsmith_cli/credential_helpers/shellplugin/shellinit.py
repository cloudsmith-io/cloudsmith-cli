# Copyright 2026 Cloudsmith Ltd
"""Shell initialisation for the package-manager shims.

Prints a snippet for ``eval "$(cloudsmith credential-helper shell-init)"`` that
prepends the Cloudsmith shims directory to ``$PATH`` so the shims shadow the
real binaries.  A single PATH prepend covers every enabled format (the shims
dir holds them all).
"""

from __future__ import annotations

import os

from .config import shims_dir


def _posix_init(path: str) -> str:
    return (
        "# Put Cloudsmith package-manager shims ahead of the real binaries\n"
        f'export PATH="{path}:$PATH"\n'
    )


def _fish_init(path: str) -> str:
    return (
        "# Put Cloudsmith package-manager shims ahead of the real binaries\n"
        f'fish_add_path "{path}"\n'
    )


_BUILDERS = {"bash": _posix_init, "zsh": _posix_init, "fish": _fish_init}


def generate_init(shell: str) -> str:
    """Return the shell-init snippet for *shell* (bash/zsh/fish)."""
    try:
        builder = _BUILDERS[shell]
    except KeyError:
        supported = ", ".join(sorted(_BUILDERS))
        raise ValueError(
            f"unsupported shell {shell!r}; choose one of: {supported}"
        ) from None
    return builder(str(shims_dir()))


def detect_shell() -> str:
    """Best-effort shell detection from ``$SHELL``, defaulting to bash."""
    name = os.path.basename(os.environ.get("SHELL", ""))
    return name if name in _BUILDERS else "bash"
