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


def _check_extra_keyring_backends(failed: list) -> None:
    """Verify keyrings.cryptfile/keyrings.alt are discoverable via entry points.

    ``cloudsmith_cli`` never imports these backend packages directly - keyring
    finds them at runtime via importlib.metadata entry points - so the
    ``cloudsmith_cli.*`` import sweep above never touches them. A missing
    dist-info directory (copy_metadata not applied) leaves them silently
    absent from discovery rather than raising, so this checks the discovered
    class list explicitly instead of relying on an import error.
    """
    import keyring.backend

    discovered = [type(b).__module__ for b in keyring.backend.get_all_keyring()]
    failed.extend(
        f"{module_prefix}: not discovered via entry points"
        for module_prefix in ("keyrings.cryptfile", "keyrings.alt")
        if not any(name.startswith(module_prefix) for name in discovered)
    )


def _check_mcp_tls_trust(failed: list) -> None:
    """Verify the MCP HTTP client's CA bundle is bundled and loadable.

    httpx2's default TLS context reads the OS trust store through OpenSSL's
    compiled-in paths, which in the frozen glibc binaries point at the build
    image's layout and miss the host's CAs. The MCP server therefore pins
    trust to certifi's bundle; this proves that bundle made it into the freeze
    and yields a verifying context, without needing network access. CA
    environment overrides are cleared so the bundled default is what's tested.
    """
    import ssl

    import cloudsmith_api

    from cloudsmith_cli.core.mcp.server import CA_BUNDLE_ENV_VARS, create_ssl_context

    saved = {
        name: os.environ.pop(name) for name in CA_BUNDLE_ENV_VARS if name in os.environ
    }
    try:
        ctx = create_ssl_context(cloudsmith_api.Configuration())
    except Exception as exc:  # pylint: disable=broad-except
        failed.append(f"mcp TLS trust: {exc!r}")
        return
    finally:
        os.environ.update(saved)

    if not isinstance(ctx, ssl.SSLContext) or ctx.verify_mode != ssl.CERT_REQUIRED:
        failed.append(f"mcp TLS trust: unexpected verify setting {ctx!r}")
    elif ctx.cert_store_stats().get("x509_ca", 0) == 0:
        failed.append("mcp TLS trust: CA bundle loaded no certificates")


def _selftest() -> int:
    """Import every bundled ``cloudsmith_cli`` module; fail on any ImportError.

    Runtime check that the freeze is complete: ``pkgutil.walk_packages``
    enumerates the package inside the onedir bundle (PyInstaller's pkgutil
    runtime hook makes this work) and each module is imported. A module the
    binary needs but PyInstaller did not collect surfaces here as an
    ImportError instead of crashing a user at runtime. Triggered only by the
    ``CLOUDSMITH_SELFTEST`` env var (set by the packaging smoketest), so it is
    never reachable as a normal CLI command. Data-file and dynamic-dispatch
    paths (which importing a module does not exercise) are covered by the
    functional smoketest steps, not here - except for the extra keyring
    backends, whose entry-point discovery is checked below, and the MCP CA
    bundle, which is loaded below.
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

    _check_extra_keyring_backends(failed)
    _check_mcp_tls_trust(failed)

    for line in failed:
        print(f"SELFTEST missing: {line}")
    print(f"SELFTEST: {'FAIL' if failed else 'OK'} ({count} modules)")
    return 1 if failed else 0


if __name__ == "__main__":
    _force_utf8_output()
    if os.environ.get("CLOUDSMITH_SELFTEST"):
        sys.exit(_selftest())
    # sys.exit() is required: AliasGroup.main runs click with
    # standalone_mode=False, so click returns the exit code (e.g. from
    # ctx.exit()) instead of raising SystemExit. The console script wraps
    # main() in sys.exit() too; a bare main() call would discard the code
    # and always exit 0.
    sys.exit(main())  # pylint: disable=no-value-for-parameter
