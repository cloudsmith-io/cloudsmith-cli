# Copyright 2026 Cloudsmith Ltd
"""
Wrapper binary for ``terraform-credentials-cloudsmith``.

This is the console entry point Terraform invokes to obtain registry
credentials.  It is a thin subprocess delegate to::

    cloudsmith credential-helper terraform <hostname>

Terraform discovers a credentials helper called "cloudsmith" as an executable
named ``terraform-credentials-cloudsmith`` on one of its default plugin search
locations, and invokes it as::

    terraform-credentials-cloudsmith [args...] <verb> <hostname>

The ``[args...]`` come from the ``args`` list in the ``credentials_helper``
block and always precede the verb.  For ``get`` they are forwarded verbatim to
``cloudsmith credential-helper terraform``, ahead of the hostname, so CLI
options such as ``--org`` and ``-P/--profile`` can be configured in
``~/.terraformrc`` instead of the environment::

    credentials_helper "cloudsmith" {
        args = ["--org=acme", "-P", "ci"]
    }

Only the ``get`` verb is delegated; ``store``/``forget`` and unknown verbs are
answered directly here with an error and a non-zero exit, matching the runtime.

See: https://developer.hashicorp.com/terraform/internals/credentials-helpers
"""

from __future__ import annotations

import subprocess
import sys

_USAGE = "Usage: terraform-credentials-cloudsmith <get|store|forget> <hostname>"


def _delegate_target() -> list[str]:
    """Return the base command the wrapper forwards a ``get`` to.

    A pip/source install resolves the bare ``cloudsmith`` command via ``PATH``.
    A frozen standalone binary (PyInstaller) is not guaranteed to be on
    ``PATH`` under that name, so point at the absolute executable instead —
    mirroring the frozen handling elsewhere in the credential helpers.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "credential-helper", "terraform"]
    return ["cloudsmith", "credential-helper", "terraform"]


def main(argv: list[str] | None = None) -> int:
    """Terraform credentials-helper entry point.

    Terraform calls this with any configured helper ``args`` followed by a verb
    and the hostname it applies to, e.g.
    ``terraform-credentials-cloudsmith --org=acme -P ci get terraform.cloudsmith.io``.
    The verb and hostname are the final two positional arguments; everything
    before them is the ``args`` list from the terraformrc block.

    For ``get`` those leading args are forwarded verbatim to
    ``cloudsmith credential-helper terraform``, ahead of the hostname, so CLI
    options such as ``--org`` and ``-P/--profile`` configured in terraformrc
    reach the delegate.

    Returns the process exit code (also used as the return value so the
    console-script shim can ``sys.exit`` on it).
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if len(args) < 2:
        print(_USAGE, file=sys.stderr)
        return 1

    # The verb and hostname are always the final two positional arguments;
    # everything before them is the helper `args` list from the terraformrc
    # block, forwarded verbatim to the delegate ahead of the hostname.
    helper_args, verb, hostname = args[:-2], args[-2], args[-1]

    if verb == "get":
        try:
            result = subprocess.run(
                [*_delegate_target(), *helper_args, hostname],
                stdin=sys.stdin,
                check=False,
            )
        except FileNotFoundError:
            print(
                "Error: 'cloudsmith' command not found. "
                "Make sure cloudsmith-cli is installed and on your PATH.",
                file=sys.stderr,
            )
            return 1
        return result.returncode

    if verb in ("store", "forget"):
        # Read and discard stdin: `store` sends a JSON object Terraform expects
        # us to fully consume before we report we cannot store it.
        try:
            if not sys.stdin.isatty():
                sys.stdin.read()
        except (OSError, ValueError):
            pass
        print(
            f"Error: '{verb}' is not supported. Credentials are managed by the "
            "Cloudsmith credential chain and cannot be stored or forgotten by "
            "this helper.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Error: Unknown verb '{verb}'. Valid verbs: get, store, forget",
        file=sys.stderr,
    )
    return 1


def run() -> None:
    """Console-script shim: run :func:`main` and exit with its return code."""
    sys.exit(main())


if __name__ == "__main__":
    run()
