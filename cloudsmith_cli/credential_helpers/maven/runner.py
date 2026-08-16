# Copyright 2026 Cloudsmith Ltd
"""Run a command with Cloudsmith credentials provisioned for it.

``cloudsmith exec -- <command>`` (or the ``mvn`` shim, which forwards to it)
lands here.  A Maven command is run against a generated ``settings.xml`` that
is deleted when the run ends; anything else runs unchanged.

The real binary is resolved with the shims directory excluded, so a shim never
re-invokes itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import config, settings

BINARY_NAMES = ("mvn", "mvnw")

# Flags that short-circuit Maven wherever they appear, so there is nothing to
# authenticate.
_SKIP_AUTH_ARGS = frozenset({"--help", "-h", "--version", "-v", "help"})

_SETTINGS_ARGS = ("-s", "--settings", "-settings")

# Maven's parser accepts long options with a single dash, so these are not the
# attached form of -s (``-smysettings.xml``) despite starting with it.
_NON_SETTINGS_S_OPTIONS = ("-show-version", "-strict-checksums")

_NOT_CONFIGURED = (
    "cloudsmith: maven is not configured; run `cloudsmith credential-helper "
    "install maven --org <org> --repo <repo>`"
)


def _canonical(path: str) -> str:
    """Normalise *path* for comparison, resolving symlinks."""
    return os.path.normcase(os.path.realpath(path))


def resolve_real_binary(binary_name: str, exclude_dir: str) -> str | None:
    """Return the first ``$PATH`` match for *binary_name* outside *exclude_dir*.

    Comparison is by real path: a PATH entry that is a symlink to the shims
    dir, or a symlink pointing at a shim, is excluded just the same.
    """
    excluded = _canonical(exclude_dir)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or _canonical(entry) == excluded:
            continue
        candidate = shutil.which(binary_name, path=entry)
        if candidate and os.path.dirname(_canonical(candidate)) != excluded:
            return candidate
    return None


def supplies_settings(args: list[str]) -> bool:
    """True when *args* already points Maven at a settings file.

    Maven's parser accepts the short option attached to its value
    (``-smysettings.xml``) as well as separated, so an exact-token match alone
    would let our injected ``-s`` shadow the user's file.
    """
    return any(
        arg in _SETTINGS_ARGS
        or arg.startswith(("--settings=", "-settings="))
        or (
            arg.startswith("-s") and len(arg) > 2 and arg not in _NON_SETTINGS_S_OPTIONS
        )
        for arg in args
    )


def _run(path: str, args: list[str]) -> int:
    """Run *path* with *args*, returning its exit code.

    A child killed by a signal comes back as a negative returncode, which is
    not an exit status: passing it to ``sys.exit`` would truncate it to the low
    8 bits (SIGKILL becoming 247 rather than 137).  It is translated to the
    shell's ``128 + signal`` convention so callers can tell an OOM kill from an
    ordinary build failure.
    """
    completed = subprocess.run([path, *args], check=False)
    if completed.returncode < 0:
        return 128 - completed.returncode
    return completed.returncode


def _wants_credentials(binary_name: str, args: list[str]) -> bool:
    """True when this invocation should be handed a generated settings.xml."""
    # A path-qualified command (`./mvnw`, `/usr/local/bin/mvn`) has to be
    # matched on its file name, or it silently runs with no credentials.
    if os.path.basename(binary_name) not in BINARY_NAMES:
        return False
    if set(args) & _SKIP_AUTH_ARGS:
        return False
    if supplies_settings(args):
        # Prepending our own -s as well would silently shadow the user's file:
        # Maven takes the first occurrence.
        print(
            "cloudsmith: warning: the command supplies its own -s/--settings "
            "file; running mvn without Cloudsmith credential injection",
            file=sys.stderr,
        )
        return False
    return True


def _usable_binding() -> config.Binding | None:
    """Return the binding to run under, or None after reporting why not.

    The shim wraps every ``mvn`` on the machine, so a missing or unusable
    binding has to be reported as a message rather than raised through the
    tool the user was actually trying to run.
    """
    try:
        binding = config.get_binding()
    except ValueError as exc:
        # A trusted [domains] table that declares no host for Maven has no
        # default to fall back on.
        print(f"cloudsmith: {exc}", file=sys.stderr)
        return None
    if binding is None or not (binding.owner and binding.repo):
        print(_NOT_CONFIGURED, file=sys.stderr)
        return None
    return binding


def run(command: list[str], credential=None) -> int:
    """Run *command*, injecting Cloudsmith credentials when it is Maven.

    Returns the child process exit code, or non-zero on a setup error.
    """
    if not command:
        print("cloudsmith: exec requires a command to run", file=sys.stderr)
        return 2

    binary_name, args = command[0], command[1:]
    real_binary = resolve_real_binary(binary_name, str(config.shims_dir()))
    if real_binary is None:
        print(f"cloudsmith: command not found: {binary_name}", file=sys.stderr)
        return 127

    if not _wants_credentials(binary_name, args):
        return _run(real_binary, args)

    binding = _usable_binding()
    if binding is None:
        return 2
    return _run_with_settings(binding, credential, real_binary, args)


def _run_with_settings(binding, credential, real_binary: str, args: list[str]) -> int:
    """Run Maven against a generated ``settings.xml``, deleted afterwards."""
    token = credential.api_key if credential else None
    if not token:
        print(
            "cloudsmith: warning: no credential resolved; private repositories "
            "will fail to authenticate — set CLOUDSMITH_API_KEY or configure OIDC",
            file=sys.stderr,
        )

    temp_dir = tempfile.mkdtemp(prefix="cloudsmith-maven-")
    try:
        path = settings.write_settings(
            temp_dir, settings.build_settings_xml(binding, token or "")
        )
    except OSError as exc:
        # A failed provisioning must not crash the wrapped tool with a
        # traceback.
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"cloudsmith: failed to provision credentials: {exc}", file=sys.stderr)
        return 1
    try:
        return _run(real_binary, ["-s", path, *args])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
