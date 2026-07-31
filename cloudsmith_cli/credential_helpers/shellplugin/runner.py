# Copyright 2026 Cloudsmith Ltd
"""Run a command with Cloudsmith credentials provisioned for it.

``cloudsmith exec -- <command>`` (or a shim that forwards to it) lands here.
The plugin is inferred from the command's binary name; when one matches we
provision ephemeral credentials, run the *real* binary (resolved with the
shims dir excluded to avoid recursion), and clean up.  Commands with no
matching plugin run unchanged.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import replace

from . import config, plugin

logger = logging.getLogger(__name__)


def _canonical(path: str) -> str:
    """Normalise *path* for comparison, resolving symlinks."""
    return os.path.normcase(os.path.realpath(path))


def resolve_real_binary(binary_name: str, exclude_dirs: list[str]) -> str | None:
    """Return the first ``$PATH`` match for *binary_name* outside *exclude_dirs*.

    Excluding the shims dir prevents a shim from re-invoking itself forever.
    Comparison is by real path: a PATH entry that is a symlink to the shims
    dir, or a symlink pointing at a shim binary, is excluded just the same.
    """
    excluded = {_canonical(d) for d in exclude_dirs}
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or _canonical(entry) in excluded:
            continue
        candidate = shutil.which(binary_name, path=entry)
        if not candidate:
            continue
        if os.path.dirname(_canonical(candidate)) in excluded:
            continue
        return candidate
    return None


def _run_process(path: str, args: list[str], env: dict[str, str]) -> int:
    """Run *path* with *args* and *env*, returning its exit code."""
    completed = subprocess.run([path, *args], env=env, check=False)
    return completed.returncode


def _resolve_entry(
    format_name: str,
    owner: str | None,
    repo: str | None,
    default_owner: str | None,
    default_repo: str | None,
) -> config.PluginEntry:
    """Load the stored entry for *format_name*, else build one from inputs.

    Explicit owner/repo (``exec --org/--repo`` flags) override the stored
    binding for this invocation. The defaults (environment-sourced values)
    apply only when nothing is stored: OIDC users keep ``CLOUDSMITH_ORG``
    exported permanently, and letting it override half of a stored binding
    would point wrapped runs at a repository that does not exist.
    """
    entry = config.get_plugin(format_name)
    if entry is None:
        return config.PluginEntry.from_dict(
            {
                "owner": owner or default_owner or "",
                "repo": repo or default_repo or "",
            }
        )
    overrides = {
        key: value for key, value in (("owner", owner), ("repo", repo)) if value
    }
    if overrides:
        entry = replace(entry, **overrides)
    return entry


def _needs_auth(args: list[str], skip_auth_args: list[str]) -> bool:
    """Return False when any arg signals an auth-free command (help/version).

    Matching anywhere in the command is intentional: these flags (e.g. Maven's
    ``--version``/``help``) short-circuit the tool regardless of position, so
    there is nothing to authenticate.
    """
    skip = set(skip_auth_args)
    return not any(arg in skip for arg in args)


def run(
    command: list[str],
    credential=None,
    owner: str | None = None,
    repo: str | None = None,
    default_owner: str | None = None,
    default_repo: str | None = None,
) -> int:
    """Run *command* with credentials provisioned for its package manager.

    Returns the child process exit code, or non-zero on a setup error.
    """
    if not command:
        print("cloudsmith: exec requires a command to run", file=sys.stderr)
        return 2

    binary_name, args = command[0], command[1:]
    real_binary = resolve_real_binary(
        binary_name, exclude_dirs=[str(config.shims_dir())]
    )
    if real_binary is None:
        print(f"cloudsmith: command not found: {binary_name}", file=sys.stderr)
        return 127

    impl = plugin.get_by_binary(binary_name)
    if impl is None or not _needs_auth(args, impl.skip_auth_args()):
        return _run_process(real_binary, args, dict(os.environ))

    skip_reason = impl.skip_provision_reason(args)
    if skip_reason:
        print(f"cloudsmith: warning: {skip_reason}", file=sys.stderr)
        return _run_process(real_binary, args, dict(os.environ))

    entry = _resolve_entry(impl.name, owner, repo, default_owner, default_repo)
    if not (entry.owner and entry.repo):
        print(
            f"cloudsmith: {impl.name} is not configured; run "
            f"`cloudsmith credential-helper install {impl.name} "
            "--org <org> --repo <repo>` or pass --org/--repo to "
            "`cloudsmith exec`",
            file=sys.stderr,
        )
        return 2

    return _provision_and_run(impl, entry, real_binary, args, credential)


def _provision_and_run(impl, entry, real_binary, args, credential) -> int:
    """Provision credentials via *impl*, run the binary, and clean up."""
    token = getattr(credential, "api_key", None) if credential else None
    if not token:
        print(
            "cloudsmith: warning: no credential resolved; private repositories "
            "will fail to authenticate — set CLOUDSMITH_API_KEY or configure OIDC",
            file=sys.stderr,
        )
    try:
        result = impl.provision(entry, token or "", args)
    except OSError as exc:
        # Boundary: a failed provisioning must not crash the wrapped tool with
        # a traceback. provision() cleans up its own temp dir before raising.
        print(f"cloudsmith: failed to provision credentials: {exc}", file=sys.stderr)
        return 1
    try:
        env = {**os.environ, **result.env}
        return _run_process(real_binary, [*result.prepend_args, *args], env)
    finally:
        for temp_dir in result.temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)
