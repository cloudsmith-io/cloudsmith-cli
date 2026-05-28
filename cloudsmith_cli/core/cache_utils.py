# Copyright 2026 Cloudsmith Ltd
"""Shared utilities for on-disk credential and cache storage."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def atomic_write_json(path: str | os.PathLike, data: Any, *, mode: int = 0o600) -> None:
    """Atomically write JSON to a file with restrictive permissions.

    Writes to a sibling temp file, fsyncs, sets mode, then renames over the
    destination. Concurrent readers never see a partial file. Temp file is
    removed on error. Caller is responsible for ensuring the parent directory
    exists.
    """
    dest = os.fspath(path)
    parent = os.path.dirname(dest) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
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
