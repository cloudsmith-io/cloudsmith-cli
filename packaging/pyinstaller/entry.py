# Copyright 2026 Cloudsmith Ltd
import importlib
import os
import pkgutil
import sys

import cloudsmith_cli
from cloudsmith_cli.cli.commands.main import main


def _force_utf8_output() -> None:
    """Prevent UnicodeEncodeError on legacy Windows consoles.

    A frozen Windows console defaults to a legacy code page (e.g. cp1252) that
    cannot encode the check/cross/warning UI glyphs the CLI prints; without
    this, commands such as ``mcp configure`` and the download progress output
    crash with UnicodeEncodeError. Reconfiguring the streams to UTF-8 is a
    no-op on POSIX (already UTF-8) and is skipped when a stream cannot be
    reconfigured (e.g. a redirected non-text stream).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass


def _selftest() -> int:
    """Import every bundled ``cloudsmith_cli`` module; fail on any ImportError.

    Runtime check that the freeze is complete: ``pkgutil.walk_packages``
    enumerates the package inside the onedir bundle (PyInstaller's pkgutil
    runtime hook makes this work) and each module is imported. A module the
    binary needs but PyInstaller did not collect surfaces here as an
    ImportError instead of crashing a user at runtime. Triggered only by the
    ``CLOUDSMITH_SELFTEST`` env var (set by the packaging smoketest), so it is
    never reachable as a normal CLI command. Data-file, dist-metadata, and
    dynamic-dispatch paths (which importing a module does not exercise) are
    covered by the functional smoketest steps, not here.
    """
    failed = []

    def _onerror(name):
        failed.append(f"{name}: {sys.exc_info()[1]!r}")

    count = 0
    for info in pkgutil.walk_packages(
        cloudsmith_cli.__path__, "cloudsmith_cli.", onerror=_onerror
    ):
        count += 1
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # pylint: disable=broad-except
            failed.append(f"{info.name}: {exc!r}")

    if count == 0:
        failed.append("walk_packages enumerated 0 modules (frozen sweep broken)")

    for line in failed:
        print(f"SELFTEST missing: {line}")
    print(f"SELFTEST: {'FAIL' if failed else 'OK'} ({count} modules)")
    return 1 if failed else 0


if __name__ == "__main__":
    _force_utf8_output()
    if os.environ.get("CLOUDSMITH_SELFTEST"):
        sys.exit(_selftest())
    main()  # pylint: disable=no-value-for-parameter
