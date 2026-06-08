# Copyright 2026 Cloudsmith Ltd
"""Shared utilities for on-disk credential and cache storage."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from typing import Any


def _atomic_write_text(dest: str, text: str, *, mode: int = 0o600) -> None:
    """Atomically write *text* to *dest* using a sibling temp file.

    Caller is responsible for ensuring the parent directory exists.
    """
    parent = os.path.dirname(dest) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, dest)
    except (OSError, TypeError, ValueError):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: str | os.PathLike, data: Any, *, mode: int = 0o600) -> None:
    """Atomically write JSON to a file with restrictive permissions.

    Writes to a sibling temp file, fsyncs, sets mode, then renames over the
    destination. Concurrent readers never see a partial file. Temp file is
    removed on error. Caller is responsible for ensuring the parent directory
    exists.
    """
    dest = os.fspath(path)
    _atomic_write_text(dest, json.dumps(data), mode=mode)


def merge_json_file(
    path: str | os.PathLike,
    mutate: Callable[[dict], None],
    *,
    backup: bool = True,
    dry_run: bool = False,
    mode: int = 0o600,
) -> bool:
    """Read a JSON object file, apply *mutate* in place, and atomically write it back.

    Parameters
    ----------
    path:
        Path to the JSON file (e.g. ``~/.docker/config.json``).
    mutate:
        Callable that receives the loaded ``dict`` and modifies it in place.
        It must not return a value; changes are applied to the dict directly.
    backup:
        When ``True`` (default) and the file already existed and content will
        change, copy the prior file to ``{path}.bak`` before writing.
    dry_run:
        When ``True``, perform the read + mutate + change-detection but make
        **no** writes (no temp file, no ``.bak``, no replace).
    mode:
        File-permission bits for the written file (default ``0o600``).

    Returns
    -------
    bool
        ``True`` if the file content changed (or would change under
        ``dry_run``), ``False`` otherwise.

    Notes
    -----
    * If the file is missing, empty, or does not parse as a JSON object
      (``dict``), the starting value is ``{}``.
    * Key order is preserved — ``sort_keys`` is **not** used.
    * The on-disk form is ``json.dumps(data, indent=2, ensure_ascii=False) + "\\n"``.
    * Parent directory is created (mode ``0o700``) if absent.

    Concurrency
    -----------
    This is a single-writer, install-time helper (used by
    ``credential-helper install/uninstall``).  The read-modify-write is
    last-writer-wins and is **NOT** safe against concurrent writers mutating
    the same file; do not use it on a hot path.  The atomic replace guarantees
    the file is never left partially written, but concurrent merges can drop
    each other's changes.
    """
    dest = os.fspath(path)

    # ------------------------------------------------------------------
    # 1. Read existing content
    # ------------------------------------------------------------------
    existing_text: str | None = None
    try:
        with open(dest, encoding="utf-8") as f:
            existing_text = f.read()
    except FileNotFoundError:
        existing_text = None

    # ------------------------------------------------------------------
    # 2. Parse → dict (treat missing/empty/non-dict/malformed as {})
    # ------------------------------------------------------------------
    data: dict = {}
    if existing_text:
        try:
            parsed = json.loads(existing_text)
            if isinstance(parsed, dict):
                data = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # ------------------------------------------------------------------
    # 3. Mutate in place
    # ------------------------------------------------------------------
    mutate(data)

    # ------------------------------------------------------------------
    # 4. Stable serialisation + change detection
    # ------------------------------------------------------------------
    new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if existing_text is not None:
        # Normalise existing content for comparison: if the file already has
        # the exact canonical form we produce, treat as no-change.
        no_change = new_text == existing_text
    else:
        no_change = False  # file didn't exist → always a change

    if no_change:
        return False

    if dry_run:
        return True

    # ------------------------------------------------------------------
    # 5. Ensure parent directory exists
    # ------------------------------------------------------------------
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)

    # ------------------------------------------------------------------
    # 6. Backup (only when file existed and content changes)
    # ------------------------------------------------------------------
    if backup and existing_text is not None:
        _atomic_write_text(dest + ".bak", existing_text, mode=0o600)

    # ------------------------------------------------------------------
    # 7. Atomic write
    # ------------------------------------------------------------------
    _atomic_write_text(dest, new_text, mode=mode)

    return True
