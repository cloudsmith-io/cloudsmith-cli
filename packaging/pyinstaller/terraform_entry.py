# Copyright 2026 Cloudsmith Ltd
"""PyInstaller entry script for the terraform-credentials-cloudsmith binary.

Produces a standalone executable named ``terraform-credentials-cloudsmith`` that
Terraform can execute directly (Terraform ignores ``.cmd`` shims on Windows and
requires a real ``.exe``). Reuses the same frozen environment as the main
``cloudsmith`` binary and forwards to the ``credential-helper terraform``
subcommand via :func:`cloudsmith_cli.wrapper.run`.
"""

import sys

# Reuse the main entry's console-encoding fix so the credentials JSON is emitted
# cleanly on legacy Windows code pages.
from entry import _force_utf8_output

from cloudsmith_cli.wrapper import run

if __name__ == "__main__":
    _force_utf8_output()
    sys.exit(run())
