# Copyright 2026 Cloudsmith Ltd
"""Named entry point for the Terraform credentials helper.

Terraform (especially on Windows) only executes a real executable named
``terraform-credentials-cloudsmith`` and ignores ``.cmd``/``.bat`` shims. This
module provides a dedicated ``main`` so the packaging layer can produce such an
executable two ways:

* ``[project.scripts]`` — ``pip install`` generates a real
  ``terraform-credentials-cloudsmith`` launcher (a genuine ``.exe`` on Windows).
* the PyInstaller spec — a second ``EXE`` target of the same name in the
  standalone bundle.

Terraform invokes the helper as
``terraform-credentials-cloudsmith [args...] <verb> <hostname>``; this wrapper
forwards those arguments unchanged to the ``credential-helper terraform``
subcommand of the main CLI.
"""

from __future__ import annotations

import sys

from .cli.commands.main import main


def run(argv: list[str] | None = None) -> int:
    """Invoke ``credential-helper terraform`` with *argv* (defaults to sys.argv).

    Returns the CLI exit code. ``AliasGroup.main`` runs Click with
    ``standalone_mode=False`` and returns the exit code rather than raising
    ``SystemExit``, so the caller is responsible for propagating it.
    """
    if argv is None:
        argv = sys.argv[1:]
    return main(  # pylint: disable=no-value-for-parameter
        args=["credential-helper", "terraform", *argv],
        prog_name="terraform-credentials-cloudsmith",
    )


def main_entry() -> None:
    """Console-script / frozen entry point: run and propagate the exit code."""
    sys.exit(run())


if __name__ == "__main__":
    main_entry()
